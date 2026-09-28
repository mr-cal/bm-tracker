"""Tests for the audit log: the allowlist, the chain, and tamper detection.

The chain is the only thing standing between "someone edited a row" and nobody
noticing, so it is tested by actually editing a row rather than by asserting
that a helper returns a string.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from bm_tracker.models import AuditLog, User
from bm_tracker.models.base import utcnow
from bm_tracker.services import audit_service as audit
from bm_tracker.services.audit_service import (
    ALLOWED_DETAIL_KEYS,
    DETAIL_MAX_CHARS,
    GENESIS_HASH,
    row_hash,
    sanitise_detail,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _user(session: AsyncSession) -> User:
    """Create and return a minimal user row.

    Args:
        session: The session to write through.

    Returns:
        The created `User`.
    """
    user = User(username="cal", display_name="Cal", timezone="UTC")
    session.add(user)
    return user


# --- the detail allowlist ------------------------------------------------


def test_detail_keeps_only_allowlisted_keys() -> None:
    """An unlisted key is dropped, not written.

    This is what stops a new column on a model from silently starting to appear
    in the audit log.
    """
    result = sanitise_detail({"day": "2026-01-09", "password_hash": "argon2id$..."})

    assert result == {"day": "2026-01-09"}
    assert "password_hash" not in (result or {})


def test_detail_drops_unserialisable_values() -> None:
    """Only scalars survive."""
    result = sanitise_detail({"count": 3, "row_count": object()})

    assert result == {"count": 3}


def test_detail_rejects_an_oversized_payload() -> None:
    """A `detail` is a few scalars; anything larger is a bug, and says so.

    Uses an allowlisted key, since an unlisted one is dropped before the cap is
    ever measured.
    """
    with pytest.raises(ValueError, match="over the"):
        sanitise_detail({"username": "x" * (DETAIL_MAX_CHARS + 1)})


def test_empty_detail_becomes_none() -> None:
    """No detail is stored as NULL rather than an empty object."""
    assert sanitise_detail(None) is None
    assert sanitise_detail({}) is None
    assert sanitise_detail({"not_allowed": 1}) is None


def test_the_allowlist_covers_the_actions_in_use() -> None:
    """Every key the test suite and services use is in the vocabulary.

    A key that is silently dropped is a record that silently loses information.
    """
    for key in ("day", "bristol_type", "n_bms", "entry_count", "username"):
        assert key in ALLOWED_DETAIL_KEYS


# --- appending and chaining ----------------------------------------------


async def test_first_row_chains_to_genesis(session: AsyncSession) -> None:
    """The first row links to a fixed value, so it verifies without a bootstrap."""
    user = _user(session)
    await session.commit()

    row = await audit.record(session, action="auth.login", user_id=user.id)
    await session.commit()

    assert row.prev_hash == GENESIS_HASH
    assert row_hash(row) != GENESIS_HASH


async def test_each_row_links_to_its_predecessor(session: AsyncSession) -> None:
    """Appending produces a verifiable chain."""
    user = _user(session)
    await session.commit()

    rows = []
    for counter in range(4):
        rows.append(
            await audit.record(
                session,
                action="day.log",
                user_id=user.id,
                entity_type="daily_log",
                entity_id=str(counter),
                detail={"day": "2026-01-09", "n_bms": counter},
            )
        )
        await session.commit()

    for previous, current in zip(rows, rows[1:]):
        assert current.prev_hash == row_hash(previous)

    intact, bad_id = await audit.verify_chain(session)
    assert intact
    assert bad_id is None


async def test_ids_are_sequential_and_not_reused(session: AsyncSession) -> None:
    """A gap-free id sequence is itself evidence that nothing was deleted."""
    user = _user(session)
    await session.commit()

    for _ in range(3):
        await audit.record(session, action="day.log", user_id=user.id)
        await session.commit()

    ids = (await session.scalars(select(AuditLog.id).order_by(AuditLog.id))).all()
    assert list(ids) == [1, 2, 3]


# --- tamper detection ----------------------------------------------------


async def test_editing_a_row_breaks_the_chain(session: AsyncSession) -> None:
    """Modifying any row invalidates every hash after it.

    The row is edited with a raw UPDATE, bypassing the ORM, because that is
    exactly what someone with database access would do.
    """
    user = _user(session)
    await session.commit()
    for _ in range(3):
        await audit.record(session, action="day.log", user_id=user.id)
        await session.commit()

    intact, _ = await audit.verify_chain(session)
    assert intact

    first = await session.scalar(select(AuditLog).order_by(AuditLog.id))
    assert first is not None
    await session.execute(
        update(AuditLog)
        .where(AuditLog.id == first.id)
        .values(action="user.delete", detail=json.dumps({"n_bms": 9999}))
    )
    await session.commit()

    intact, bad_id = await audit.verify_chain(session)
    assert not intact
    assert bad_id is not None


async def test_deleting_a_row_breaks_the_chain(session: AsyncSession) -> None:
    """Removing a row leaves its successor pointing at a hash nothing produces."""
    user = _user(session)
    await session.commit()
    for _ in range(3):
        await audit.record(session, action="day.log", user_id=user.id)
        await session.commit()

    middle = await session.scalar(
        select(AuditLog).order_by(AuditLog.id).offset(1).limit(1)
    )
    assert middle is not None
    await session.delete(middle)
    await session.commit()

    intact, _ = await audit.verify_chain(session)
    assert not intact


async def test_detail_is_stored_as_sorted_json(session: AsyncSession) -> None:
    """Deterministic serialisation, or the hash would depend on dict order."""
    user = _user(session)
    await session.commit()

    row = await audit.record(
        session,
        action="day.log",
        user_id=user.id,
        detail={"n_bms": 2, "day": "2026-01-09"},
    )
    await session.commit()

    assert row.detail == '{"day":"2026-01-09","n_bms":2}'


async def test_detail_excludes_secrets_end_to_end(session: AsyncSession) -> None:
    """A password hash offered as detail never reaches the table.

    The allowlist is the mechanism; this is the property that matters, checked
    through the real write path rather than the sanitiser alone.
    """
    user = _user(session)
    await session.commit()

    await audit.record(
        session,
        action="auth.login",
        user_id=user.id,
        detail={"status": "ok", "password_hash": "argon2id$secret", "notes": "diary"},
    )
    await session.commit()

    stored = await session.scalar(select(AuditLog.detail))
    assert stored == '{"status":"ok"}'
    assert "argon2id" not in (stored or "")
    assert "diary" not in (stored or "")


# --- pruning -------------------------------------------------------------


async def test_prune_removes_old_rows_and_keeps_the_rest(session: AsyncSession) -> None:
    """Retention drops from the front, so the survivors still chain."""
    user = _user(session)
    await session.commit()

    old = await audit.record(session, action="day.log", user_id=user.id)
    old.at = utcnow() - timedelta(days=500)
    await session.commit()

    for _ in range(3):
        await audit.record(session, action="day.log", user_id=user.id)
        await session.commit()

    removed = await audit.prune(session, retention_days=400)
    await session.commit()
    assert removed == 1

    surviving = (await session.scalars(select(AuditLog).order_by(AuditLog.id))).all()
    assert len(surviving) == 3


async def test_survivors_still_chain_after_pruning(session: AsyncSession) -> None:
    """Verification anchors on the last pruned row, as documented.

    A full-chain check from genesis reports a break at the first survivor, which
    is expected rather than a problem — so the API makes the anchor explicit
    rather than silently reporting false alarms.
    """
    user = _user(session)
    await session.commit()

    for _ in range(2):
        row = await audit.record(session, action="day.log", user_id=user.id)
        row.at = utcnow() - timedelta(days=500)
        await session.commit()
    for _ in range(3):
        await audit.record(session, action="day.log", user_id=user.id)
        await session.commit()

    await audit.prune(session, retention_days=400)
    await session.commit()

    survivors = (await session.scalars(select(AuditLog).order_by(AuditLog.id))).all()
    first_survivor = survivors[0]

    intact, bad_id = await audit.verify_chain(session, since_id=first_survivor.id - 1)
    assert intact, f"chain broke at id {bad_id}"


async def test_audit_at_is_ordered_within_the_same_second(
    session: AsyncSession,
) -> None:
    """Rows written in a tight loop still hash deterministically.

    `at` has microsecond resolution, so two rows never collide on the field the
    hash is computed from.
    """
    user = _user(session)
    await session.commit()

    first = await audit.record(session, action="day.log", user_id=user.id)
    second = await audit.record(session, action="day.log", user_id=user.id)
    await session.commit()

    assert isinstance(first.at, datetime)
    assert first.at != second.at
