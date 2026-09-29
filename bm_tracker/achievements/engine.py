"""Evaluating the registry and recording unlocks.

The engine is deliberately dumb: read some facts, ask each achievement, write
what is newly satisfied. Everything interesting lives in `rules.py`,
`registry.py` and `facts.py`, so that adding achievement #301 never requires
understanding this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from bm_tracker.achievements import facts as facts_module
from bm_tracker.achievements import registry as registry_module
from bm_tracker.models import AchievementUnlock, User
from bm_tracker.models.base import utcnow

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from bm_tracker.achievements.registry import Achievement, Registry

#: Loaded once at import. Validated there, so a malformed registry fails the
#: process at startup rather than producing achievements that never unlock.
REGISTRY: Registry = registry_module.load()


@dataclass(frozen=True, slots=True)
class Unlock:
    """An achievement that has been earned."""

    achievement: Achievement
    points: int
    unlocked_at: datetime


@dataclass(frozen=True, slots=True)
class Status:
    """One achievement's state for a user, for rendering the collection page."""

    achievement: Achievement
    unlocked: bool
    unlocked_at: datetime | None
    progress: float | None
    current: float | None
    target: float | None

    @property
    def points(self) -> int:
        """Return the achievement's point value."""
        return self.achievement.points

    @property
    def count(self) -> str:
        """Return the measured count as "9 / 10", or an empty string.

        Shown instead of a bar where the shortfall is not a distance. It says
        the same thing without implying the gap can be walked.
        """
        if self.current is None or self.target is None:
            return ""
        return f"{self.current:g} / {self.target:g}"


async def _unlocked_keys(
    session: AsyncSession, user_id: int, year: int
) -> dict[str, datetime]:
    """Return the keys a user has already earned this year.

    Args:
        session: The session to read through.
        user_id: Whose unlocks.
        year: The calendar year.

    Returns:
        A mapping of achievement key to the time it was earned.

    """
    rows = (
        await session.scalars(
            select(AchievementUnlock).where(
                AchievementUnlock.user_id == user_id,
                AchievementUnlock.year == year,
            )
        )
    ).all()
    return {row.achievement_key: row.unlocked_at for row in rows}


async def evaluate(
    session: AsyncSession,
    user: User,
    year: int,
    *,
    window_minutes: int = 10,
) -> list[Unlock]:
    """Work out what a user has earned but not yet been credited for.

    Idempotent: an achievement already in `achievement_unlocks` for the year is
    never returned again, so the engine can run on every write and on every read
    without producing duplicates.

    Args:
        session: The session to read through.
        user: The user to evaluate.
        year: The calendar year.
        window_minutes: The ten-minute bonus window, so the facts agree with the
            leaderboard's.

    Returns:
        The newly satisfied `Unlock`s.

    """
    have = await _unlocked_keys(session, user.id, year)
    fact_set = await facts_module.build(
        session, user, year, window_minutes=window_minutes
    )

    fresh: list[Unlock] = []
    for achievement in REGISTRY.achievements:
        if achievement.key in have:
            continue
        unlocked = achievement.evaluate(fact_set).unlocked
        if unlocked:
            fresh.append(
                Unlock(
                    achievement=achievement,
                    points=achievement.points,
                    unlocked_at=utcnow(),
                )
            )
    return fresh


async def record(
    session: AsyncSession, unlocks: list[Unlock], user_id: int, year: int
) -> int:
    """Persist unlocks and credit their points.

    Args:
        session: The session to write through.
        unlocks: The unlocks to record.
        user_id: Who earned them.
        year: The year they were earned in.

    Returns:
        How many rows were written.

    """
    for unlock in unlocks:
        session.add(
            AchievementUnlock(
                user_id=user_id,
                achievement_key=unlock.achievement.key,
                year=year,
                points=unlock.points,
                unlocked_at=unlock.unlocked_at,
            )
        )
    return len(unlocks)


async def status_for(
    session: AsyncSession,
    user: User,
    year: int,
    *,
    window_minutes: int = 10,
) -> list[Status]:
    """Return every achievement with its state, for the collection page.

    Every achievement is listed, earned or not — the catalogue is the fun part,
    and a wall of 300 locked icons with no names is duller than one that says
    "Blatherer: ten in a single day".

    Args:
        session: The session to read through.
        user: Whose collection.
        year: The calendar year.
        window_minutes: The ten-minute bonus window.

    Returns:
        The `Status` list, in registry order.

    """
    have = await _unlocked_keys(session, user.id, year)
    fact_set = await facts_module.build(
        session, user, year, window_minutes=window_minutes
    )

    statuses: list[Status] = []
    for achievement in REGISTRY.achievements:
        verdict = achievement.evaluate(fact_set)
        earned = achievement.key in have
        statuses.append(
            Status(
                achievement=achievement,
                unlocked=earned,
                unlocked_at=have.get(achievement.key),
                progress=1.0 if earned else verdict.progress,
                current=None if earned else verdict.current,
                target=None if earned else verdict.target,
            )
        )
    return statuses


async def earned_points(session: AsyncSession, user_id: int, year: int) -> int:
    """Return the total achievement points a user has earned this year.

    Args:
        session: The session to read through.
        user_id: Whose points.
        year: The calendar year.

    Returns:
        The sum of the points on their unlocks.

    """
    rows = (
        await session.scalars(
            select(AchievementUnlock.points).where(
                AchievementUnlock.user_id == user_id,
                AchievementUnlock.year == year,
            )
        )
    ).all()
    return sum(rows)


async def rebuild(session: AsyncSession, year: int, *, window_minutes: int = 10) -> int:
    """Recompute every user's facts and unlocks for a year from raw data.

    Needed when a new fact is added to `facts.py`: users who existed before it
    have no value for it, and their achievements would otherwise stay locked
    forever. Not a migration — a command.

    Args:
        session: The session to write through.
        year: The calendar year.
        window_minutes: The ten-minute bonus window.

    Returns:
        How many unlocks were created.

    """
    users = (await session.scalars(select(User))).all()
    written = 0
    for user in users:
        fact_set = await facts_module.build(
            session, user, year, window_minutes=window_minutes
        )
        await facts_module.store(session, user.id, year, fact_set)
        fresh = await evaluate(session, user, year, window_minutes=window_minutes)
        written += await record(session, fresh, user.id, year)
    return written


__all__ = [
    "REGISTRY",
    "Status",
    "Unlock",
    "earned_points",
    "evaluate",
    "rebuild",
    "record",
    "status_for",
]
