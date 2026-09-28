"""The group feed.

One reverse-chronological, year-scoped list of what the group did: notes, points
earned, and achievement unlocks. Exactly the three things §4.7 permits, so the
feed and the privacy model cannot drift apart.

Derived, not stored. A `UNION ALL` across the three sources, read through the
same derivation the leaderboard uses, so a points figure in the feed is the same
number the leaderboard counted rather than a second implementation of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from sqlalchemy.sql.elements import ColumnElement

if TYPE_CHECKING:
    from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bm_tracker import scoring
from bm_tracker.achievements.engine import REGISTRY
from bm_tracker.achievements.registry import RegistryError
from bm_tracker.models import AchievementUnlock, BmEntry, DailyLog, User
from bm_tracker.services import visibility
from bm_tracker.timezones import year_bounds

PAGE_SIZE = 30


def _window(year: int | None) -> tuple[date | None, date | None]:
    """Return the bounds to filter a year by, or None bounds for all time.

    The feed is one continuous timeline now rather than a year at a time, so a
    `None` year means "do not filter" rather than "this year". Every query that
    took a year takes this instead, so a caller cannot half-apply the filter.

    Args:
        year: A calendar year, or None for every year.

    Returns:
        The inclusive lower and upper day bounds, either of which may be None.

    """
    if year is None:
        return None, None
    start, end = year_bounds(year)
    return start, end


def _in_range(
    column: ColumnElement[Any], year: int | None
) -> list[ColumnElement[bool]]:
    """Return the day predicates for a year, or none for all time.

    Args:
        column: The day column to compare against.
        year: A calendar year, or None for every year.

    Returns:
        A list suitable for splatting into a `where()`.

    """
    start, end = _window(year)
    if start is None or end is None:
        return []
    return [column >= start, column <= end]


KIND_POINTS = "points"
KIND_NOTE = "note"
KIND_ACHIEVEMENT = "achievement"
KIND_BM = "bm"
KIND_DAY = "day"

# What the template compares `item.kind` against, so a rename in one place
# cannot silently fall through to the catch-all branch in the other.
KINDS = SimpleNamespace(
    points=KIND_POINTS,
    note=KIND_NOTE,
    achievement=KIND_ACHIEVEMENT,
    bm=KIND_BM,
    day=KIND_DAY,
)


@dataclass(frozen=True, slots=True)
class FeedItem:
    """One event in the feed.

    Other people's BMs appear as no field at all — no time, no Bristol type, no
    strain, no backfill marker — because those are not things other users see.
    The single exception is `entry`, which is populated only for the viewer's
    own items and is what the homepage's "your history" section is built from.
    """

    kind: str
    at: datetime
    user: User
    year: int
    points: int | None = None
    text: str | None = None
    achievement_key: str | None = None
    name: str | None = None

    # The viewer's own entry, for the one item kind that carries BM detail.
    # Populated *only* when `user` is the viewer, so a serialised item can never
    # carry someone else's time or Bristol type: the rule is enforced where the
    # item is built rather than trusted to the template.
    entry: BmEntry | None = None
    day: date | None = None

    # The registry's own wording for an achievement item, so the feed and the
    # badges page cannot describe the same unlock differently.
    achievement: dict[str, str] | None = None

    @property
    def display_name(self) -> str:
        """Return the name to show for the actor."""
        return self.user.display_name


async def _users_by_id(session: AsyncSession) -> dict[int, User]:
    """Return every user keyed by id.

    Args:
        session: The session to read through.

    Returns:
        A mapping of id to `User`.

    """
    return {user.id: user for user in (await session.scalars(select(User))).all()}


async def _scores_for(
    session: AsyncSession,
    users: list[User],
    year: int,
    window_minutes: int,
) -> dict[int, scoring.UserScore]:
    """Return each user's derived score for the year.

    Args:
        session: The session to read through.
        users: The users to score.
        year: The calendar year.
        window_minutes: The ten-minute bonus window.

    Returns:
        A mapping of user id to `UserScore`.

    """
    return {
        user.id: await scoring.score_year(
            session, user, year, window_minutes=window_minutes
        )
        for user in users
    }


async def feed_items(
    session: AsyncSession,
    *,
    viewer: User,
    limit: int = PAGE_SIZE,
    offset: int = 0,
) -> list[FeedItem]:
    """Return a page of activity, newest first, shaped by who is looking.

    One continuous timeline rather than a year at a time: paging back far enough
    crosses 1 January without a seam or a selector to change. That is why there
    is no `year` argument — the boundary is not a thing this feed has.

    The viewer's own BMs and empty days appear in full — time, type, strain,
    urgency, flags — because that is the history worth reading. Everyone else
    contributes only notes and achievements, which is the whole of what the
    privacy model in the plan says other people get to see.

    The asymmetry is built here rather than in the template. A view of the feed
    that is viewer-dependent is easy to get subtly wrong from the template side,
    where a missing condition shows someone else's Bristol type rather than
    nothing at all.

    Args:
        session: The session to read through.
        viewer: Who is looking. Their own items get the full treatment.
        limit: How many items to return.
        offset: How many items to skip, for the page being asked for.

    Returns:
        The `FeedItem`s, newest first.

    """
    users = await _users_by_id(session)
    if not users:
        return []

    # Each source is asked for enough to cover the requested page. Fetching one
    # page's worth per source and then merging would silently truncate any
    # source with more items than that, which is the common case, not the rare
    # one.
    depth = offset + limit
    # The group, limited to what other people are allowed to see.
    items = await _notes(session, users, limit=depth)
    items.extend(await _achievements(session, users, limit=depth))

    # The viewer, in full. The viewer's own notes and achievements are already
    # in the two calls above, so these add only what nobody else may see.
    items.extend(await _own_entries(session, viewer, limit=depth))
    items.extend(await _own_days(session, viewer, limit=depth))

    items.sort(key=lambda item: item.at, reverse=True)
    return items[offset : offset + limit]


def _badge(key: str) -> dict[str, str] | None:
    """Return the registry's wording for an achievement.

    Args:
        key: The achievement key.

    Returns:
        Its name, description, icon and tier, or None if the registry has no
        such key — which it should not, but a feed that 500s because a
        definition was retired is worse than one missing a badge.

    """
    try:
        definition = REGISTRY.get(key)
    except RegistryError:
        return None
    return {
        "name": definition.name,
        "description": definition.description,
        "icon": definition.icon,
        "tier": definition.tier,
    }


async def _own_entries(
    session: AsyncSession,
    viewer: User,
    limit: int,
) -> list[FeedItem]:
    """Return the viewer's own BMs, newest first.

    No points figure: a BM does not earn points, the day it belongs to does, and
    putting a number here would be a second derivation of it that could drift
    from the leaderboard. The badge bar already shows the day's real total.

    This is the only place in the feed that carries BM detail, and it is only
    ever called with the viewer as the owner. Everything else about the feed is
    shaped by what other people are allowed to see.

    Args:
        session: The session to read through.
        viewer: Whose entries to return.
        limit: The most to return.

    Returns:
        The viewer's own `FeedItem`s, newest first.

    """
    rows = (
        await session.execute(
            select(BmEntry, DailyLog)
            .join(DailyLog, DailyLog.id == BmEntry.daily_log_id)
            .where(DailyLog.user_id == viewer.id)
            .order_by(BmEntry.created_at.desc(), BmEntry.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        FeedItem(
            kind=KIND_BM,
            at=entry.created_at,
            user=viewer,
            year=day.day.year,
            entry=entry,
            day=day.day,
        )
        for entry, day in rows
    ]


async def _own_days(
    session: AsyncSession,
    viewer: User,
    limit: int,
) -> list[FeedItem]:
    """Return the days the viewer logged that had no BMs on them.

    A "nothing happened today" entry is the whole scoring premise, so it belongs
    in a view of one's own history. Without it a run of empty days simply does
    not exist anywhere on the screen.

    Args:
        session: The session to read through.
        viewer: Whose days to return.
        limit: The most to return.

    Returns:
        The viewer's own day `FeedItem`s, newest first.

    """
    rows = (
        await session.scalars(
            select(DailyLog)
            .where(
                DailyLog.user_id == viewer.id,
                DailyLog.n_bms == 0,
            )
            .order_by(DailyLog.logged_at.desc(), DailyLog.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        FeedItem(
            kind=KIND_DAY,
            at=row.logged_at,
            user=viewer,
            year=row.day.year,
            day=row.day,
        )
        for row in rows
    ]


async def _notes(
    session: AsyncSession,
    users: dict[int, User],
    limit: int,
) -> list[FeedItem]:
    """Return note items, using only notes that are live.

    A superseded note is retained for its owner but is not published: the day is
    described by its entries, and re-publishing an overtaken note would put
    something the user has implicitly replaced back in front of everyone.

    Args:
        session: The session to read through.
        users: Users keyed by id.
        limit: The most to return, across every user.

    Returns:
        The note `FeedItem`s.

    """
    items: list[FeedItem] = []

    live_day_notes = (
        await session.scalars(
            select(DailyLog)
            .where(
                DailyLog.n_bms == 0,
                DailyLog.notes.is_not(None),
            )
            .order_by(DailyLog.logged_at.desc())
            .limit(limit)
        )
    ).all()
    for row in live_day_notes:
        if not row.notes or not row.notes.strip():
            continue
        user = users.get(row.user_id)
        if user is None:
            continue
        items.append(
            FeedItem(
                kind=KIND_NOTE,
                at=row.logged_at,
                user=user,
                year=row.day.year,
                text=row.notes.strip(),
                points=scoring.POINTS_NOTE,
            )
        )

    # `execute`, not `scalars`: scalars() would return only the first entity of
    # the pair, and the day is needed to attribute the note to a user.
    entry_notes = (
        await session.execute(
            select(BmEntry, DailyLog)
            .join(DailyLog, DailyLog.id == BmEntry.daily_log_id)
            .where(BmEntry.notes.is_not(None))
            .order_by(BmEntry.created_at.desc())
            .limit(limit)
        )
    ).all()
    for entry, day in entry_notes:
        if not entry.notes or not entry.notes.strip():
            continue
        user = users.get(day.user_id)
        if user is None:
            continue
        items.append(
            FeedItem(
                kind=KIND_NOTE,
                at=entry.created_at,
                user=user,
                year=day.day.year,
                text=entry.notes.strip(),
                points=scoring.POINTS_NOTE,
            )
        )

    return items


async def _achievements(
    session: AsyncSession,
    users: dict[int, User],
    limit: int,
) -> list[FeedItem]:
    """Return achievement unlocks for the year.

    Args:
        session: The session to read through.
        users: Users keyed by id.
        limit: The most to return, across every user.

    Returns:
        The achievement `FeedItem`s.

    """
    rows = (
        await session.scalars(
            select(AchievementUnlock)
            .order_by(AchievementUnlock.unlocked_at.desc())
            .limit(limit)
        )
    ).all()
    items: list[FeedItem] = []
    for row in rows:
        user = users.get(row.user_id)
        if user is None:
            continue
        items.append(
            FeedItem(
                kind=KIND_ACHIEVEMENT,
                at=row.unlocked_at,
                user=user,
                year=row.year,
                achievement_key=row.achievement_key,
                achievement=_badge(row.achievement_key),
                points=row.points,
            )
        )
    return items


async def points_for_year(
    session: AsyncSession,
    year: int,
    window_minutes: int = 10,
) -> dict[int, int]:
    """Return each user's total logging points for the year.

    Used to render the points-awarded items, which are derived from the same
    score the leaderboard uses rather than recomputed per event.

    Args:
        session: The session to read through.
        year: The calendar year.
        window_minutes: The ten-minute bonus window.

    Returns:
        A mapping of user id to logging points.

    """
    users = (await session.scalars(select(User))).all()
    scores = await _scores_for(session, list(users), year, window_minutes)
    return {uid: score.logging_points for uid, score in scores.items()}


def to_public_dict(item: FeedItem) -> dict[str, object]:
    """Project a feed item to what a viewer may see.

    Args:
        item: The item to project.

    Returns:
        A mapping containing only public keys.

    """
    payload: dict[str, object] = {
        "kind": item.kind,
        "at": item.at,
        "user": item.user.id,
        "display_name": item.display_name,
        "year": item.year,
    }
    if item.text is not None:
        payload["text"] = item.text
    if item.points is not None:
        payload["points"] = item.points
    if item.achievement_key is not None:
        payload["achievement_key"] = item.achievement_key
    if item.name is not None:
        payload["name"] = item.name
    visibility.assert_public(payload)
    return payload


__all__ = [
    "FeedItem",
    "KIND_ACHIEVEMENT",
    "KIND_NOTE",
    "KIND_POINTS",
    "PAGE_SIZE",
    "feed_items",
    "to_public_dict",
]
