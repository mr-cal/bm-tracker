"""Deterministic fake data for local development and the e2e suite.

Two rules shape the distributions here, and both come from wanting the seeded
data to look like a group that has actually been using the app:

- The distributions match the real ones rather than being uniformly random. A
  day is logged same-day about 78% of the time, most logged days have no BMs at
  all, and Bristol types cluster on 3-5 the way real ones do. A uniform
  generator produces data that makes the scoring look wrong.
- Nothing is fabricated after the fact. Achievements come from the real engine,
  so the seeded state is exactly what the rules produce rather than a set of
  plausible-looking badges.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bm_tracker import auth, bristol
from bm_tracker.models import (
    AchievementUnlock,
    BmEntry,
    DailyLog,
    User,
    UserFact,
    utcnow,
)
from bm_tracker.services import bm_service
from bm_tracker.settings import Settings
from bm_tracker.timezones import today_for

DEFAULT_USERS = 8

# Two years, so the history crosses 1 January and the feed's continuous
# timeline has a year boundary to cross in it. Anything shorter stops inside the
# current year, which is exactly the case the timeline was built to avoid and
# therefore the one worth being able to look at.
DEFAULT_DAYS = 730

# How much history the first account gets. The others get all of it, so the feed
# has a two-year timeline with a year boundary in it; the first account gets
# enough to have a streak and a tier of achievements and no more.
#
# The reason is the Legendary reveal. Tiers unlock at a lifetime points
# threshold — 1,100 for Legendary — and a full 730 days of logging is worth
# around 7,000 points, so a uniformly seeded admin sails past every gate and the
# collection page is a wall of unlocked icons. That demonstrates nothing. The
# gates themselves are the interesting part: they are what makes the Legendary
# achievements feel like somewhere to get to rather than a list to grind, and
# you cannot see a gate working if everything is already open.
#
# So the admin is deliberately short of it, at roughly a tenth of a year's
# logging. Sign in as the admin to see the collection mid-progress, which is the
# state a real user is in for most of their first month.
DEFAULT_DEMO_DAYS = 75
DEFAULT_PASSWORD = "e2e-password"

# Weighted Bristol types. Real distributions cluster hard on 3-5; the tails are
# present so the rare achievements are reachable in seeded data.
BRISTOL_WEIGHTS: dict[int, int] = {
    1: 6,
    2: 7,
    3: 20,
    4: 30,
    5: 15,
    6: 15,
    7: 7,
}

NOTES = (
    "long flight, nothing happened",
    "ate a whole curry, regret nothing",
    "gentle one after a big coffee",
    "the spicy one hit",
    "stood up too fast",
    "queued the wrong way round",
    "this is becoming a habit",
    "very good, no notes",
    "everything is fine, nothing is fine",
    "after three beers",
)

TIMEZONES = ("Europe/London", "Europe/London", "America/New_York", "UTC")

# The distributions below are the point of the seeder: a uniform generator makes
# the scoring look wrong, because real history is lumpy.
P_CHANCE_DAY_LOGGED = 0.82
P_BACKFILLED = 0.12
P_DAY_HAS_NOTE = 0.35
P_QUICK_ENTRY = 0.08
P_SPICY = 0.18

# The first seeded account's today is a five-BM day, and its last
# entry is logged late at night. Five in a day is The Marathon and
# a 23:30 entry is Late Night Larry, so one day satisfies both
# rules at once — the moment the feed renders as a single card:
# "unlocked 2 achievements".
#
# A seeded history has usually earned the reachable achievements
# already, so a day that earns two together is staged on purpose
# rather than left to chance.
DEMO_TODAY_BMS = 5
DEMO_UNLOCKS: tuple[tuple[str, str], ...] = (
    ("marathon", "The Marathon"),
    ("night_owl", "Late Night Larry"),
)
# How often a BM is recorded as urgent. Rare on purpose.
P_URGENT = 0.12
# Strain is optional, so most entries do not have it. The plan says ~60%.
P_STRAIN_RECORDED = 0.6
P_EMPTY_DAY = 0.55
BM_COUNT_WEIGHTS = [60, 30, 10]
BM_COUNTS = [1, 2, 3]


@dataclass(frozen=True, slots=True)
class SeedResult:
    """What a seeding run produced."""

    users: int
    days: int
    bms: int
    notes: int
    backfills: int
    quick_entries: int
    unlocks: int
    # What the next log will earn, kept for anyone who wants to say so out loud.
    next_unlock: str | None = None


def _weighted_type(rng: random.Random) -> int:
    """Return a Bristol type drawn from the realistic distribution.

    Args:
        rng: The seeded random source.

    Returns:
        A type, 1-7.

    """
    return rng.choices(list(BRISTOL_WEIGHTS), weights=list(BRISTOL_WEIGHTS.values()))[0]


def _strain(rng: random.Random, bristol_type: int) -> int | None:
    """Return a strain level for an entry, or None if it went unrecorded.

    Strain is optional, so a real history has gaps: about four in ten entries
    never had it filled in. Where it was, it tracks the Bristol type, because
    a hard, lumpy result is hard to pass. Drawing them independently would seed
    a history where type 1 arrives effortlessly, which no one would believe.

    Args:
        rng: The seeded random source.
        bristol_type: The type this entry was given.

    Returns:
        A level 1-3, or None for "not recorded".

    """
    if rng.random() > P_STRAIN_RECORDED:
        return None
    if bristol_type <= bristol.BAND_HARD_MAX:
        return rng.choices([2, 3], weights=[0.3, 0.7])[0]
    if bristol_type <= bristol.BAND_NORMAL_MAX:
        return rng.choices([1, 2], weights=[0.6, 0.4])[0]
    return 1


async def _clear(session: AsyncSession) -> None:
    """Remove every row the app owns, children first.

    Args:
        session: The session to write through.

    """
    for model in (BmEntry, DailyLog, UserFact, AchievementUnlock, User):
        await session.execute(delete(model))
    await session.commit()


async def seed(
    session: AsyncSession,
    *,
    users: int = DEFAULT_USERS,
    days: int = DEFAULT_DAYS,
    seed_value: int = 42,
    password: str = DEFAULT_PASSWORD,
    now: datetime | None = None,
) -> SeedResult:
    """Fill a database with a plausible group and its history.

    Deterministic given a `now`: the same `seed_value`, `users` and `days` and
    the same instant produce the same history, which is what lets the test suite
    and the e2e run assert on it. Two columns are deliberately outside that:
    `password_hash` carries a random salt, and `created_at` is stamped by the
    clock rather than derived from the seed.

    "Given a `now`" is doing real work in that sentence. Nothing is ever written
    down in the future, so the rows for the current day are clamped to the
    present, and without an injected instant that ceiling is the real clock. The
    counts are identical either way; only the timestamps on today's handful of
    rows move, and a history that ended yesterday would be the wrong kind of
    plausible.

    Args:
        session: The session to write through.
        users: How many people to create. The first is an admin.
        days: How many days of history to generate, ending today.
        seed_value: The random seed.
        password: The password every generated account gets.
        now: The instant to treat as the present. Injected by the tests,
            because the interesting failures happen only at a date boundary
            between timezones, and a test that only breaks at midnight is a
            test that never runs.

    Returns:
        A `SeedResult` describing what was written.

    """
    # Standard-library RNG, not a cryptographic one: the point is reproducible
    # fake data, and seeding from a fixed value must be stable across runs.
    rng = random.Random(seed_value)  # noqa: S311
    await _clear(session)

    names = (
        "cal",
        "bee",
        "sam",
        "jay",
        "dee",
        "ell",
        "fay",
        "gus",
        "hal",
        "ivy",
    )[:users]

    accounts: list[User] = []
    for index, name in enumerate(names):
        user = User(
            username=name,
            display_name=name.title(),
            password_hash=auth.hash_password(password),
            is_admin=(index == 0),
            timezone=rng.choice(TIMEZONES),
        )
        session.add(user)
        accounts.append(user)
    await session.flush()

    total_days = 0
    total_bms = 0
    total_notes = 0
    total_backfills = 0
    total_quick = 0

    # The instant the seed treats as the present, as naive UTC — the
    # frame every stored timestamp is written in. Nothing is ever
    # written down in the future, so rows for the current day are
    # clamped to it.
    ceiling = now.astimezone(ZoneInfo("UTC")).replace(tzinfo=None) if now else utcnow()

    for position, user in enumerate(accounts):
        # Only the first account is staged for a demo unlock. A demo that fires
        # for one person is a demo; one that fires for all eight is noise.
        is_demo = position == 0
        # The first account is the one you sign into, so its history is sized to
        # leave the Legendary tier locked. See DEFAULT_DEMO_DAYS.
        user_days = DEFAULT_DEMO_DAYS if is_demo else days
        # Each user's "today" is their own. Computing one date for the whole
        # group means someone in a western timezone is handed a day they have
        # not reached yet, and `log_nothing_today` rightly refuses it.
        today = today_for(user.timezone, now=now)
        for offset in range(user_days, -1, -1):
            day = today - timedelta(days=offset)
            # The demo day is never a missed day: the whole point is that the
            # next log lands on an achievement, and a seeded gap would leave the
            # account with nothing to add to.
            if not (is_demo and offset == 0) and rng.random() > P_CHANCE_DAY_LOGGED:
                # The odd missed day, so streaks vary the way real ones do.
                continue
            total_days += 1

            backfilled = rng.random() < P_BACKFILLED
            logged_at = datetime(day.year, day.month, day.day, 20, 0)
            if backfilled:
                logged_at = logged_at + timedelta(days=rng.randint(1, 4))
                total_backfills += 1
            # Nothing is ever written down in the future. `check_not_future`
            # guards the *day*, but a backfill offset or the 20:00 evening hour
            # can still put the moment of writing after now — which put entries
            # up to four days ahead at the top of a feed sorted newest-first.
            logged_at = min(logged_at, ceiling)

            note = rng.choice(NOTES) if rng.random() < P_DAY_HAS_NOTE else None
            if note:
                total_notes += 1

            if not (is_demo and offset == 0) and rng.random() < P_EMPTY_DAY:
                await bm_service.log_nothing_today(
                    session, user, day, notes=note, logged_at=logged_at
                )
                continue

            count = rng.choices(BM_COUNTS, weights=BM_COUNT_WEIGHTS)[0]
            if is_demo and offset == 0:
                count = DEMO_TODAY_BMS
            quick = rng.random() < P_QUICK_ENTRY
            for index in range(count):
                hour = rng.randint(6, 22)
                minute = rng.choice([0, 15, 30, 45])
                if is_demo and offset == 0 and index == count - 1:
                    # The demo day's last BM is the one after dark:
                    # it is what earns Late Night Larry alongside
                    # The Marathon.
                    hour, minute = 23, 30
                occurred = datetime(day.year, day.month, day.day, hour, minute)
                # A quick entry is written minutes after it
                # happened; otherwise the day is logged in the
                # evening. `occurred` is wall clock in the owner's
                # timezone, and `created_at` is stored as naive UTC
                # like every other timestamp, so the moment of
                # writing is the same instant expressed in UTC —
                # and never after the present.
                if quick:
                    created = (
                        (
                            occurred.replace(tzinfo=ZoneInfo(user.timezone))
                            + timedelta(minutes=rng.randint(1, 9))
                        )
                        .astimezone(ZoneInfo("UTC"))
                        .replace(tzinfo=None)
                    )
                else:
                    created = logged_at
                created = min(created, ceiling)
                chosen = _weighted_type(rng)
                await bm_service.log_bm(
                    session,
                    user,
                    day,
                    occurred_local=occurred,
                    bristol_type=chosen,
                    spicy=rng.random() < P_SPICY,
                    urgent=rng.random() < P_URGENT,
                    strain=_strain(rng, chosen),
                    # Only one entry per day carries the day's note, and only
                    # when the day has BMs — otherwise the day-note is
                    # superseded and never pays.
                    notes=note if (index == 0 and note) else None,
                    logged_at=logged_at,
                    created_at=created,
                )
                total_bms += 1
                if quick:
                    total_quick += 1

    await session.commit()

    # Achievements come from the real engine rather than being fabricated, so the
    # seeded collection is exactly what the rules produce. `rebuild` rather than
    # a hand-rolled loop, so the facts are persisted too.
    from bm_tracker.achievements import engine as achievements  # noqa: PLC0415

    unlocks = await achievements.rebuild(session, today.year)
    await _backdate_unlocks(session, accounts, now=now)
    # The demo day is the one moment the seeder stages on purpose:
    # two achievements earned by the same day, stamped at the
    # moment that day was logged so the feed shows them as one
    # card rather than two, months apart.
    await _stage_demo_unlocks(session, accounts[0], now=now)

    await session.commit()

    return SeedResult(
        users=len(accounts),
        days=total_days,
        bms=total_bms,
        notes=total_notes,
        backfills=total_backfills,
        quick_entries=total_quick,
        unlocks=unlocks,
    )


async def _backdate_unlocks(
    session: AsyncSession,
    users: list[User],
    now: datetime | None = None,
) -> None:
    """Move seeded unlocks back to when they were plausibly earned.

    The engine stamps every unlock with the moment it evaluated, so a freshly
    seeded database has a hundred unlocks all sharing one timestamp. Sorted by
    time, they then sit above the genuine history and the feed's first page is
    nothing but badges.

    Each user's unlocks are spread across their own logged days in ascending
    point order, so the easy ones land early and the legendary ones late. The
    exact instant is not knowable from the outside; what matters is that it sits
    somewhere in the history rather than all in one pile at the end.
    """
    for user in users:
        today = today_for(user.timezone, now=now)
        rows = (
            await session.scalars(
                select(AchievementUnlock)
                .where(
                    AchievementUnlock.user_id == user.id,
                )
                .order_by(AchievementUnlock.points, AchievementUnlock.achievement_key)
            )
        ).all()
        if not rows:
            continue

        # The day's own `logged_at`, not its date at 20:00: that timestamp is
        # already clamped to the present, so reusing it cannot put an unlock in
        # the future. Recomputing 20:00 here did exactly that for today, and
        # only started doing it often once there were enough unlocks to land on
        # the last day. The spread stops at yesterday: today is the demo day,
        # staged at its own moment, and the highest unlock landing beside the
        # staged pair would claim it earned them company.
        days = list(
            (
                await session.execute(
                    select(DailyLog.day, DailyLog.logged_at)
                    .where(DailyLog.user_id == user.id, DailyLog.day < today)
                    .order_by(DailyLog.day)
                )
            ).all()
        )
        if not days:
            continue

        for index, row in enumerate(rows):
            position = int((index + 0.5) * len(days) / len(rows))
            _, logged_at = days[min(position, len(days) - 1)]
            row.unlocked_at = logged_at


async def _stage_demo_unlocks(
    session: AsyncSession,
    demo: User,
    now: datetime | None = None,
) -> None:
    """Stamp the demo day's two unlocks at the moment that day was logged.

    The demo account's today is a five-BM day whose last entry is
    late at night, so the engine earns The Marathon and Late Night
    Larry on the same day. `_backdate_unlocks` cannot know that: it
    spreads every unlock evenly across the history, which would put
    the pair in different months and the feed would never show them
    together.

    Both were first satisfied today — the rest of the history holds
    at most three BMs a day, and no other entry is ever logged
    after 22:00 — so the day's own `logged_at` is the plausible
    moment, not just a staged one.

    Args:
        session: The session to write through.
        demo: The first seeded account.
        now: The instant the seed treats as the present.

    """
    today = today_for(demo.timezone, now=now)
    logged_at = await session.scalar(
        select(DailyLog.logged_at).where(
            DailyLog.user_id == demo.id, DailyLog.day == today
        )
    )
    if logged_at is None:
        return
    keys = [key for key, _ in DEMO_UNLOCKS]
    rows = (
        await session.scalars(
            select(AchievementUnlock).where(
                AchievementUnlock.user_id == demo.id,
                AchievementUnlock.achievement_key.in_(keys),
            )
        )
    ).all()
    for row in rows:
        row.unlocked_at = logged_at


def _resolved_path(database_url: str) -> Path | None:
    """Return the filesystem path a SQLite URL points at.

    Args:
        database_url: The configured database URL.

    Returns:
        The absolute path, or `None` for a non-file or in-memory database.

    """
    for prefix in ("sqlite+aiosqlite:///", "sqlite+pysqlite:///"):
        if database_url.startswith(prefix):
            raw = database_url.removeprefix(prefix)
            return None if not raw or raw == ":memory:" else Path(raw).resolve()
    return None


def is_safe_to_seed(database_url: str) -> bool:
    """Return whether a database may be wiped by the seeder.

    Wiping is destructive, and the production file is *also* called
    `bm_tracker.db`, so a filename check would be actively unsafe. Seeding is
    permitted only for an in-memory database, a path containing `e2e`, or the
    exact path the app uses for local development by default.

    Args:
        database_url: The configured database URL.

    Returns:
        Whether seeding is permitted.

    """
    if ":memory:" in database_url:
        return True
    path = _resolved_path(database_url)
    if path is None:
        return False
    if "e2e" in path.name.lower():
        return True
    default = _resolved_path(str(Settings.model_fields["database_url"].default))
    return default is not None and path == default
