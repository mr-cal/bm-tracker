"""Tests for the schema: constraints, cascade behaviour and note supersession.

These exercise the rules the database enforces, rather than the service layer
that will later rely on them. A constraint that is not tested here is a
constraint nobody has checked actually fires.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from bm_tracker.models import BmEntry, DailyLog, User
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


def _naive(day: date, hour: int = 7) -> datetime:
    """Return a naive wall-clock datetime on the given day.

    Args:
        day: The date.
        hour: The hour of day.

    Returns:
        A naive datetime, matching how `occurred_local` is stored.
    """
    return datetime(day.year, day.month, day.day, hour, 0, 0)


async def _user(session: AsyncSession, username: str = "cal") -> User:
    """Create and return a minimal user row.

    Args:
        session: The session to write through.
        username: The account's username.

    Returns:
        The created `User`.
    """
    user = User(username=username, display_name=username.title(), timezone="UTC")
    session.add(user)
    await session.commit()
    return user


async def _day(session: AsyncSession, user: User, day: date, **kwargs) -> DailyLog:
    """Create and return a daily log row.

    Args:
        session: The session to write through.
        user: The owner.
        day: The occurrence date.
        **kwargs: Extra `DailyLog` column values.

    Returns:
        The created `DailyLog`.
    """
    log = DailyLog(user_id=user.id, day=day, logged_at=datetime(2026, 1, 1), **kwargs)
    session.add(log)
    await session.commit()
    return log


# --- constraints ---------------------------------------------------------


async def test_one_row_per_user_per_day(
    session: AsyncSession, test_engine: AsyncEngine
) -> None:
    """Two rows for the same user and day must be rejected.

    This constraint is what makes "this day is logged" a single fact rather than
    a tally, and it is what a "nothing today" day is built on.
    """
    user = await _user(session)
    await _day(session, user, date(2026, 1, 9))

    session.add(
        DailyLog(user_id=user.id, day=date(2026, 1, 9), logged_at=datetime(2026, 1, 9))
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_different_users_may_log_the_same_day(session: AsyncSession) -> None:
    """The uniqueness is per user, not global."""
    one = await _user(session, "one")
    two = await _user(session, "two")

    await _day(session, one, date(2026, 1, 9))
    await _day(session, two, date(2026, 1, 9))

    total = await session.scalar(select(func.count()).select_from(DailyLog))
    assert total == 2


async def test_usernames_are_unique(session: AsyncSession) -> None:
    """Two accounts may not share a username, or /people/{username} is ambiguous."""
    await _user(session, "cal")

    session.add(User(username="cal", display_name="Impostor", timezone="UTC"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_negative_bm_count_is_rejected(session: AsyncSession) -> None:
    """`n_bms` is a count and cannot go negative."""
    user = await _user(session)

    session.add(
        DailyLog(
            user_id=user.id,
            day=date(2026, 1, 9),
            n_bms=-1,
            logged_at=datetime(2026, 1, 9),
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.parametrize("bristol_type", [0, 8, -1])
async def test_bristol_type_outside_the_scale_is_rejected(
    session: AsyncSession, bristol_type: int
) -> None:
    """The Bristol scale is 1-7, and the database says so."""
    user = await _user(session)
    day = await _day(session, user, date(2026, 1, 9))
    occurred = _naive(day.day)

    session.add(
        BmEntry(
            daily_log_id=day.id,
            occurred_local=occurred,
            bristol_type=bristol_type,
            created_at=datetime(2026, 1, 9, 7, 5),
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_spicy_is_the_only_optional_field(session: AsyncSession) -> None:
    """Nothing is required beyond a time and a type, so the form stays short."""
    user = await _user(session)
    day = await _day(session, user, date(2026, 1, 9))

    entry = BmEntry(
        daily_log_id=day.id,
        occurred_local=_naive(day.day),
        bristol_type=4,
        created_at=datetime(2026, 1, 9, 7, 5),
    )
    session.add(entry)
    await session.commit()

    assert entry.spicy is None
    assert entry.notes is None


# --- cascade -------------------------------------------------------------


async def test_deleting_a_day_cascades_to_its_entries(
    session: AsyncSession, test_engine: AsyncEngine
) -> None:
    """`ON DELETE CASCADE` must actually fire.

    This only works because the app sets PRAGMA foreign_keys=ON on every
    connection. Without it SQLite treats the constraint as inert and orphans
    accumulate with no error at all.
    """
    user = await _user(session)
    day = await _day(session, user, date(2026, 1, 9))
    session.add(
        BmEntry(
            daily_log_id=day.id,
            occurred_local=_naive(day.day),
            bristol_type=4,
            created_at=datetime(2026, 1, 9, 7, 5),
        )
    )
    await session.commit()

    # Prove the pragma is on for this connection, so a pass here means the
    # cascade worked rather than the test being vacuous.
    pragma = await session.scalar(text("PRAGMA foreign_keys"))
    assert pragma == 1

    await session.delete(day)
    await session.commit()

    remaining = await session.scalar(select(func.count()).select_from(BmEntry))
    assert remaining == 0


async def test_deleting_a_user_cascades_to_their_days(session: AsyncSession) -> None:
    """A user's rows go with them."""
    user = await _user(session)
    await _day(session, user, date(2026, 1, 9))
    await _day(session, user, date(2026, 1, 10))

    await session.delete(user)
    await session.commit()

    remaining = await session.scalar(select(func.count()).select_from(DailyLog))
    assert remaining == 0


# --- note supersession ----------------------------------------------------


async def test_day_note_is_live_on_an_empty_day(session: AsyncSession) -> None:
    """A "nothing today" day carries a live note."""
    user = await _user(session)
    day = await _day(
        session, user, date(2026, 1, 9), notes="long flight, nothing happened"
    )

    assert day.is_note_live
    assert not day.is_superseded


async def test_day_note_is_superseded_once_a_bm_exists(session: AsyncSession) -> None:
    """Adding the first BM supersedes the note — by arithmetic, with no write.

    Nothing is stored to record the supersession: `n_bms` going from 0 to 1 is
    the whole mechanism, which is why it cannot fall out of step.
    """
    user = await _user(session)
    day = await _day(session, user, date(2026, 1, 9), notes="nothing happened")
    assert day.is_note_live

    session.add(
        BmEntry(
            daily_log_id=day.id,
            occurred_local=_naive(day.day),
            bristol_type=6,
            created_at=datetime(2026, 1, 9, 7, 5),
        )
    )
    day.n_bms = 1
    await session.commit()
    await session.refresh(day)

    assert not day.is_note_live
    assert day.is_superseded
    # The text is retained, not discarded.
    assert day.notes == "nothing happened"


async def test_day_note_revives_when_the_last_bm_is_deleted(
    session: AsyncSession,
) -> None:
    """The reverse transition, and equally write-free."""
    user = await _user(session)
    day = await _day(session, user, date(2026, 1, 9), notes="nothing happened")
    entry = BmEntry(
        daily_log_id=day.id,
        occurred_local=_naive(day.day),
        bristol_type=6,
        created_at=datetime(2026, 1, 9, 7, 5),
    )
    session.add(entry)
    day.n_bms = 1
    await session.commit()
    await session.refresh(day)
    assert day.is_superseded

    await session.delete(entry)
    day.n_bms = 0
    await session.commit()
    await session.refresh(day)

    assert day.is_note_live


async def test_whitespace_note_is_neither_live_nor_superseded(
    session: AsyncSession,
) -> None:
    """A stray space is not a diary entry."""
    user = await _user(session)
    day = await _day(session, user, date(2026, 1, 9), notes="   ")

    assert not day.is_note_live
    assert not day.is_superseded


async def test_entry_note_is_always_live(session: AsyncSession) -> None:
    """A note attached to a specific BM is not subject to supersession."""
    user = await _user(session)
    day = await _day(session, user, date(2026, 1, 9))
    entry = BmEntry(
        daily_log_id=day.id,
        occurred_local=_naive(day.day),
        bristol_type=6,
        notes="the urgent one",
        created_at=datetime(2026, 1, 9, 7, 5),
    )
    session.add(entry)
    await session.commit()

    assert entry.has_note


async def test_whitespace_entry_note_does_not_count(session: AsyncSession) -> None:
    """Same rule for a per-BM note."""
    user = await _user(session)
    day = await _day(session, user, date(2026, 1, 9))
    entry = BmEntry(
        daily_log_id=day.id,
        occurred_local=_naive(day.day),
        bristol_type=6,
        notes=" \n ",
        created_at=datetime(2026, 1, 9, 7, 5),
    )
    session.add(entry)
    await session.commit()

    assert not entry.has_note


async def test_entry_delay_is_absolute(session: AsyncSession) -> None:
    """A time typed slightly ahead of the clock still counts as close.

    The quick-entry bonus compares absolute difference, so a user who writes
    "07:00" and submits at 06:57 is not penalised for a rounding slip.
    """
    user = await _user(session)
    day = await _day(session, user, date(2026, 1, 9))
    entry = BmEntry(
        daily_log_id=day.id,
        occurred_local=datetime(2026, 1, 9, 7, 0),
        bristol_type=4,
        created_at=datetime(2026, 1, 9, 6, 57),
    )
    session.add(entry)
    await session.commit()

    assert entry.entry_delay_seconds == pytest.approx(-180)


# --- misc -----------------------------------------------------------------


async def test_user_cannot_authenticate_without_a_password(
    session: AsyncSession,
) -> None:
    """A provisioned-but-never-redeemed account exists but cannot sign in."""
    user = await _user(session)

    assert user.password_hash is None
    assert not user.can_authenticate

    user.password_hash = "argon2id$redacted"
    assert user.can_authenticate

    user.is_active = False
    assert not user.can_authenticate


async def test_achievement_unlocks_are_keyed_by_year(session: AsyncSession) -> None:
    """The same achievement can be earned again in a later year.

    A Perfect Week in 2026 is a different achievement from 2025, which is the
    same fresh-start rule that bounds streaks. A lifetime key would put the
    2025 badge permanently in 2026's "locked" column at 100% progress.
    """
    from bm_tracker.models import AchievementUnlock  # noqa: PLC0415

    user = await _user(session)
    session.add_all(
        [
            AchievementUnlock(
                user_id=user.id, achievement_key="perfect_week", year=2025, points=5
            ),
            AchievementUnlock(
                user_id=user.id, achievement_key="perfect_week", year=2026, points=5
            ),
        ]
    )
    await session.commit()

    total = await session.scalar(
        select(func.count())
        .select_from(AchievementUnlock)
        .where(AchievementUnlock.achievement_key == "perfect_week")
    )
    assert total == 2


async def test_user_facts_accept_an_arbitrary_key(session: AsyncSession) -> None:
    """Key/value, so a new fact is not a migration."""
    from bm_tracker.models import UserFact  # noqa: PLC0415

    user = await _user(session)
    session.add_all(
        [
            UserFact(user_id=user.id, fact_key="bm_count_total", fact_value=412.0),
            UserFact(user_id=user.id, fact_key="bm_count_day", fact_value=2.0),
        ]
    )
    await session.commit()

    value = await session.scalar(
        select(UserFact.fact_value).where(
            UserFact.user_id == user.id, UserFact.fact_key == "bm_count_total"
        )
    )
    assert value == 412.0


async def test_audit_rows_survive_the_user_they_describe(
    session: AsyncSession,
) -> None:
    """`audit_log` has no foreign key, so deleting a user keeps the record.

    The alternative — cascading — would destroy the evidence of the deletion,
    which is the one moment the log most needs to survive.
    """
    from bm_tracker.models import AuditLog  # noqa: PLC0415
    from sqlalchemy import insert  # noqa: PLC0415

    user = await _user(session)
    await session.execute(
        insert(AuditLog).values(
            at=datetime(2026, 1, 1),
            user_id=user.id,
            action="user.delete",
            entity_type="user",
            entity_id=str(user.id),
            detail=None,
            prev_hash="0" * 64,
        )
    )
    await session.commit()

    await session.delete(user)
    await session.commit()

    remaining = await session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "user.delete")
    )
    assert remaining == 1


async def test_timestamps_default_to_naive_utc(
    session: AsyncSession,
) -> None:
    """Stored timestamps are naive UTC, so string ordering is chronological.

    SQLite has no datetime type; SQLAlchemy writes ISO-8601 strings, and the
    lexicographic ordering that every date comparison relies on is only correct
    if the format is uniform.
    """
    user = await _user(session)
    day = await _day(session, user, date(2026, 1, 9))

    assert day.created_at.tzinfo is None
    assert day.logged_at.tzinfo is None
    now = datetime.now().replace(tzinfo=None)
    assert abs(day.created_at - now) < timedelta(minutes=5)
