"""Tests for the seeder.

Two properties matter and both are easy to break by accident: the data must be
reproducible from a seed value, and the destructive guard must refuse anything
that is not obviously throwaway. A seeder that points itself at production is
the worst bug this module could have.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from bm_tracker import auth
from bm_tracker.achievements import engine
from bm_tracker.models import AchievementUnlock, BmEntry, DailyLog, User
from bm_tracker.routes.stats import _lifetime_points
from bm_tracker.services import seed_service
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def test_seeding_creates_the_expected_shape(session: AsyncSession) -> None:
    """Eight people, a plausible amount of history, and every account usable."""
    result = await seed_service.seed(session, users=8, days=60, seed_value=1)

    assert result.users == 8
    assert result.days > 0
    assert result.bms > 0

    users = (await session.scalars(select(User))).all()
    assert len(users) == 8
    assert sum(1 for u in users if u.is_admin) == 1
    for user in users:
        assert user.password_hash is not None
        assert auth.verify_password(seed_service.DEFAULT_PASSWORD, user.password_hash)


async def test_seeding_is_deterministic(session: AsyncSession) -> None:
    """The same seed and the same instant produce the same data, byte for byte.

    The instant is injected rather than left to the clock, and that is the whole
    point of the assertion: the seeder clamps today's rows to the present, so
    without a fixed `now` two runs seconds apart differ by a handful of
    timestamps. Comparing counts alone would pass either way and catch nothing.
    """
    from datetime import datetime  # noqa: PLC0415

    moment = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)
    first = await seed_service.seed(
        session, users=4, days=40, seed_value=99, now=moment
    )
    rows_first = await _all_rows(session)

    second = await seed_service.seed(
        session, users=4, days=40, seed_value=99, now=moment
    )
    rows_second = await _all_rows(session)

    assert first == second
    assert rows_first == rows_second


async def test_a_different_seed_produces_different_data(
    session: AsyncSession,
) -> None:
    """Otherwise "deterministic" would just mean "ignores the seed"."""
    await seed_service.seed(session, users=3, days=40, seed_value=1)
    one = await _type_histogram(session)

    await seed_service.seed(session, users=3, days=40, seed_value=2)
    two = await _type_histogram(session)

    assert one != two


async def _all_rows(session: AsyncSession) -> list[tuple[object, ...]]:
    """Return every seeded row, ordered, for an exact comparison.

    Args:
        session: The session to read through.

    Returns:
        One tuple per row across every table the seeder writes.

    """
    rows: list[tuple[object, ...]] = []
    for model in (User, DailyLog, BmEntry, AchievementUnlock):
        columns = [
            c.name
            for c in model.__table__.columns
            # Two columns can never match between runs and are not seeder
            # content: the argon2 salt in `password_hash`, which is random by
            # design, and `created_at`, which is stamped by the database clock
            # rather than derived from the seed. Comparing them would make this
            # test fail forever rather than catch anything.
            if c.name not in ("password_hash", "created_at")
        ]
        found = await session.scalars(select(model).order_by(*columns))
        rows.extend(tuple(getattr(row, name) for name in columns) for row in found)
    return rows


async def _all_counts(session: AsyncSession) -> dict[str, int]:
    """Return row counts per table.

    Args:
        session: The session to read through.

    Returns:
        A mapping of table name to row count.
    """
    return {
        "users": await session.scalar(select(func.count()).select_from(User)),
        "days": await session.scalar(select(func.count()).select_from(DailyLog)),
        "entries": await session.scalar(select(func.count()).select_from(BmEntry)),
    }


async def _type_histogram(session: AsyncSession) -> dict[int, int]:
    """Return the Bristol-type distribution across every entry.

    Args:
        session: The session to read through.

    Returns:
        A mapping of type to count.
    """
    rows = (await session.execute(select(BmEntry.bristol_type))).all()
    histogram: dict[int, int] = {}
    for (value,) in rows:
        histogram[value] = histogram.get(value, 0) + 1
    return histogram


async def test_seeding_replaces_rather_than_accumulates(
    session: AsyncSession,
) -> None:
    """Running it twice does not double the data."""
    await seed_service.seed(session, users=3, days=30, seed_value=7)
    first = await _all_counts(session)

    await seed_service.seed(session, users=3, days=30, seed_value=7)

    assert await _all_counts(session) == first


async def test_backfills_and_quick_entries_both_appear(
    session: AsyncSession,
) -> None:
    """Both rare paths are represented, so the UI for them is exercised."""
    result = await seed_service.seed(session, users=6, days=120, seed_value=5)

    assert result.backfills > 0, "no backfills seeded"
    assert result.quick_entries > 0, "no quick entries seeded"
    assert result.notes > 0, "no notes seeded"


async def test_every_day_is_a_valid_score(
    session: AsyncSession,
) -> None:
    """Seeded data must not contain anything the scorer would reject."""
    from bm_tracker import scoring  # noqa: PLC0415

    users = (await session.scalars(select(User).order_by(User.username))).all()
    for user in users:
        score = await scoring.score_year(session, user, 2026)
        assert score.logging_points >= 0
        assert score.current_streak <= score.longest_streak
        assert score.qualifying_days <= score.days_logged


# --- the destructive guard -----------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "sqlite+aiosqlite:///:memory:",
        "sqlite+aiosqlite:///./data/bm_tracker.db",
        "sqlite+aiosqlite:////tmp/whatever/e2e.db",
    ],
)
def test_seeding_is_allowed_for_throwaway_databases(url: str) -> None:
    """In-memory, the local default, and anything named for e2e."""
    assert seed_service.is_safe_to_seed(url)


@pytest.mark.parametrize(
    "url",
    [
        # The production file has the *same name* as the local one, so a
        # filename check would wave this through.
        "sqlite+aiosqlite:////data/bm_tracker.db",
        "sqlite+aiosqlite:////var/lib/production.sqlite",
        "postgresql+asyncpg://user:pass@host/bm_tracker",
    ],
)
def test_seeding_is_refused_for_anything_else(url: str) -> None:
    """Anything that is not obviously a scratch database."""
    assert not seed_service.is_safe_to_seed(url)


async def test_the_guard_cannot_be_bypassed_by_relocation(
    session: AsyncSession,
) -> None:
    """A file merely called `bm_tracker.db` outside the local path is refused."""
    assert not seed_service.is_safe_to_seed("sqlite+aiosqlite:////data/bm_tracker.db")


# --- the date-boundary case ----------------------------------------------


async def test_seeding_works_across_a_date_boundary(
    session: AsyncSession,
) -> None:
    """Every user is seeded against *their own* today, not a group-wide one.

    The instant below is one where London has already rolled over and New York has
    not. A seeder that computed one date for the whole group would hand the New
    York user a day they had not reached, and the service layer would correctly
    refuse it — which is exactly how this was found, by running it at half past
    eleven at night.

    The clock is injected because otherwise the bug only reproduces for an hour a
    day, and a test that only fails at midnight is a test that never runs.
    """
    from datetime import datetime  # noqa: PLC0415

    from bm_tracker.services.seed_service import TIMEZONES  # noqa: PLC0415
    from bm_tracker.timezones import today_for  # noqa: PLC0415

    moment = datetime(2026, 9, 27, 23, 30, tzinfo=UTC)

    # Confirm the instant still straddles a boundary for the zones the seeder
    # draws from, so this test cannot quietly stop testing anything.
    assert len({today_for(zone, now=moment) for zone in TIMEZONES}) > 1

    # The regression is that seeding *raised*. With the old group-wide date and
    # this instant, it raises on every run of this test.
    result = await seed_service.seed(
        session, users=8, days=20, seed_value=3, now=moment
    )
    assert result.days > 0

    # Read the users back: seeding clears and recreates them, so anything held
    # from before the call refers to rows that no longer exist.
    by_id = {user.id: user for user in await session.scalars(select(User))}
    for row in await session.scalars(select(DailyLog)):
        user = by_id[row.user_id]
        # Measured against the real clock, which is what the service checks.
        assert row.day <= today_for(user.timezone), (
            f"{user.username} ({user.timezone}) was given {row.day}, "
            "which is in their future"
        )


async def test_seeding_never_writes_a_row_in_the_future(
    session: AsyncSession,
) -> None:
    """Nothing in the seeded history is dated after the instant we seeded at.

    `check_not_future` guards the *day* a BM belongs to, but the moment it was
    written is separate: an evening's 20:00, or a backfill offset of up to four
    days, can both land after now. That put entries days ahead at the top of a
    feed sorted newest-first, so the first page opened on a date that had not
    happened.
    """
    from bm_tracker.models import (  # noqa: PLC0415
        AchievementUnlock,
        BmEntry,
        DailyLog,
        User,
    )

    moment = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)
    await seed_service.seed(session, users=4, days=40, seed_value=11, now=moment)

    future_bms = (
        await session.scalars(
            select(BmEntry).where(BmEntry.created_at > moment.replace(tzinfo=None))
        )
    ).all()
    # `logged_at` is naive *local* wall clock, the owner's own, so it has to be
    # compared against that owner's local now rather than against UTC.
    zones = {u.id: u.timezone for u in await session.scalars(select(User))}
    future_days = [
        row
        for row in await session.scalars(select(DailyLog))
        if row.logged_at
        > moment.astimezone(ZoneInfo(zones[row.user_id])).replace(tzinfo=None)
    ]
    # Compared in the owner's own frame, like the days above it. `unlocked_at`
    # is naive local time, so eight in the evening in Honolulu is six the next
    # morning in UTC — which is correct, and not something to assert against.
    future_unlocks = [
        row
        for row in await session.scalars(select(AchievementUnlock))
        if row.unlocked_at
        > moment.astimezone(ZoneInfo(zones[row.user_id])).replace(tzinfo=None)
    ]

    assert not future_bms, f"{len(future_bms)} BMs are dated in the future"
    assert not future_days, f"{len(future_days)} days are dated in the future"
    assert not future_unlocks, f"{len(future_unlocks)} unlocks are dated in the future"


async def test_seeding_leaves_the_next_log_one_achievement_away(
    session: AsyncSession,
) -> None:
    """After `make dev-seed`, logging one BM earns something.

    A seeded history has usually earned the reachable achievements already, so
    the person using it never sees an unlock happen — and the reward screen
    exists for that one moment. The first account gets exactly four entries
    today, which puts The Marathon (five in a day) one entry out.

    This is also the test that the *engine* agrees, rather than the seeder
    merely intending to: it evaluates the rules against the seeded facts.
    """
    from bm_tracker.achievements import engine  # noqa: PLC0415
    from bm_tracker.models import User  # noqa: PLC0415
    from bm_tracker.services import bm_service  # noqa: PLC0415
    from bm_tracker.timezones import today_for  # noqa: PLC0415

    result = await seed_service.seed(
        session, users=3, days=30, seed_value=5, password="x" * 16
    )
    assert result.next_unlock is None, "the field was dropped, not just unused"

    first = (
        await session.scalars(
            select(User).where(User.username == "cal").order_by(User.id)
        )
    ).one()
    today = today_for(first.timezone)

    before = await engine.status_for(session, first, today.year)
    assert not any(
        s.unlocked and s.achievement.key == seed_service.DEMO_UNLOCK_KEY for s in before
    ), "the demo achievement should still be unearned after seeding"

    await bm_service.log_bm(
        session,
        first,
        today,
        occurred_local=datetime(today.year, today.month, today.day, 12, 0),
        bristol_type=3,
    )
    # The same two calls the log route makes, so this checks the path a real
    # log takes rather than the rules in isolation.
    await engine.record(
        session, await engine.evaluate(session, first, today.year), first.id, today.year
    )
    await session.commit()

    after = await engine.status_for(session, first, today.year)
    assert any(
        s.unlocked and s.achievement.key == seed_service.DEMO_UNLOCK_KEY for s in after
    ), f"logging one BM did not earn {seed_service.DEMO_UNLOCK_NAME}"


async def test_the_admin_is_left_short_of_the_top_tier(session: AsyncSession) -> None:
    """The seeded first account must not sail past every reveal threshold.

    A uniformly seeded admin unlocks everything, which makes the collection page
    a wall of lit icons and the reveal gates invisible. Signing in as the admin
    is how you look at the app, so the admin is the account that has to show the
    gates working.
    """
    await seed_service.seed(session, users=8)

    admin = await session.scalar(select(User).where(User.username == "cal"))
    points = await _lifetime_points(session, admin, 10)
    revealed = engine.REGISTRY.points_to_reveal("legendary")

    assert points < revealed, (
        f"admin has {points} points, legendary reveals at {revealed}"
    )
    assert points >= engine.REGISTRY.points_to_reveal("rare"), (
        "the page should still have tiers to show"
    )
