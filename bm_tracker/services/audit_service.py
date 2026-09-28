"""The only writer to the audit log.

Everything here exists to make three failure modes impossible rather than
merely unlikely: a secret reaching the log, a row being altered, and an
unbounded table.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult

from bm_tracker.models.audit_log import RETENTION_DAYS, AuditLog
from bm_tracker.models.base import utcnow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# The chain starts from a fixed value so the first row is verifiable without a
# separate bootstrap step.
GENESIS_HASH: Final = "0" * 64

# A `detail` blob larger than this is a bug, not a record. The cap is what turns
# "somebody serialised a whole object" into a loud failure.
DETAIL_MAX_CHARS: Final = 512

# The complete vocabulary of keys permitted in `detail`. Anything else is
# dropped rather than written, so adding a field to a model cannot accidentally
# start serialising it.
ALLOWED_DETAIL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "achievement_key",
        "bristol_type",
        "count",
        "day",
        "entry_count",
        "n_bms",
        "points",
        "reason",
        "row_count",
        "status",
        "table",
        "user_count",
        "username",
        "year",
    }
)


def sanitise_detail(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return only the allowlisted, serialisable parts of a detail mapping.

    Values that cannot be JSON-serialised, and keys outside the vocabulary, are
    dropped. The result is checked against the length cap.

    Args:
        detail: The candidate detail mapping, or `None`.

    Returns:
        A JSON-safe mapping, or `None` if nothing survived.

    Raises:
        ValueError: If the sanitised detail exceeds `DETAIL_MAX_CHARS`. That is
            a programming error — a `detail` is a handful of scalars.

    """
    if not detail:
        return None

    kept: dict[str, Any] = {}
    for key, value in detail.items():
        if key not in ALLOWED_DETAIL_KEYS:
            continue
        if isinstance(value, bool | int | float | str) or value is None:
            kept[key] = value

    if not kept:
        return None

    encoded = json.dumps(kept, sort_keys=True, separators=(",", ":"))
    if len(encoded) > DETAIL_MAX_CHARS:
        msg = (
            f"audit detail is {len(encoded)} chars, over the "
            f"{DETAIL_MAX_CHARS} cap. detail takes a few scalars, not an object."
        )
        raise ValueError(msg)
    return kept


def compute_hash(
    *,
    at: datetime,
    user_id: int | None,
    action: str,
    entity_type: str | None,
    entity_id: str | None,
    detail: str | None,
    prev_hash: str,
) -> str:
    """Return the chain hash for one row.

    Derived from the row's own fields plus the previous row's hash, so walking
    the table in `id` order and recomputing verifies the whole chain. The row's
    hash is not stored; it does not need to be.

    Args:
        at: When the row was written.
        user_id: The actor, or `None`.
        action: The action name.
        entity_type: The affected entity type, or `None`.
        entity_id: The affected entity id, or `None`.
        detail: The already-serialised detail, or `None`.
        prev_hash: The previous row's hash, or the genesis value.

    Returns:
        A hex SHA-256 digest.

    """
    payload = json.dumps(
        {
            "at": at.isoformat(),
            "user_id": user_id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "detail": detail,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def row_hash(row: AuditLog) -> str:
    """Return the chain hash of an existing row.

    Args:
        row: The row to hash.

    Returns:
        Its hex SHA-256 chain hash.

    """
    return compute_hash(
        at=row.at,
        user_id=row.user_id,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        detail=row.detail,
        prev_hash=row.prev_hash,
    )


async def record(
    session: AsyncSession,
    *,
    action: str,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one entry to the audit log.

    This is the only function in the codebase permitted to insert into
    `audit_log`, and there is deliberately no counterpart that updates or
    deletes a row.

    Args:
        session: The session to write through. Not committed here; the caller
            owns the transaction, so an audited change and its audit row commit
            together or not at all.
        action: The action name, e.g. "bm.create".
        user_id: The actor, or `None` for anonymous or system actions.
        entity_type: The affected entity type, or `None`.
        entity_id: The affected entity id, or `None`.
        detail: A few allowlisted scalars describing the change.

    Returns:
        The appended `AuditLog` row.

    """
    safe_detail = sanitise_detail(detail)
    encoded = (
        json.dumps(safe_detail, sort_keys=True, separators=(",", ":"))
        if safe_detail
        else None
    )

    last = await session.scalar(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))
    prev = row_hash(last) if last is not None else GENESIS_HASH
    at = utcnow()

    entry = AuditLog(
        at=at,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=encoded,
        prev_hash=prev,
    )
    session.add(entry)
    return entry


async def verify_chain(
    session: AsyncSession,
    *,
    since_id: int | None = None,
) -> tuple[bool, int | None]:
    """Recompute the chain from an anchor and report whether it is intact.

    Args:
        session: The session to read through.
        since_id: Verify only rows after this `id`, starting from that row's own
            hash. Needed after `prune`, which removes rows from the front and so
            breaks the link to the genesis value.

    Returns:
        `(is_intact, first_bad_id)`. `first_bad_id` is the `id` of the earliest
        row whose `prev_hash` does not match its predecessor, or `None` when the
        chain is intact.

    """
    statement = select(AuditLog).order_by(AuditLog.id)
    if since_id is not None:
        anchor = await session.get(AuditLog, since_id)
        if anchor is None:
            return True, None
        expected_prev = row_hash(anchor)
        statement = statement.where(AuditLog.id > since_id)
    else:
        expected_prev = GENESIS_HASH

    for row in (await session.scalars(statement)).all():
        if row.prev_hash != expected_prev:
            return False, row.id
        expected_prev = row_hash(row)
    return True, None


async def prune(session: AsyncSession, *, retention_days: int = RETENTION_DAYS) -> int:
    """Delete rows older than the retention window.

    The one sanctioned deletion. It removes from the *front* of the chain, never
    the middle, so the surviving rows still form an unbroken chain among
    themselves — but the link back to the genesis value is gone. Verify the
    remainder with `verify_chain(since_id=<new first id>)`; a full-chain
    verification from genesis will report a break at the first surviving row,
    which is expected rather than a problem.

    Args:
        session: The session to delete through.
        retention_days: How many days of history to keep.

    Returns:
        The number of rows removed.

    """
    cutoff = utcnow() - timedelta(days=retention_days)
    result = await session.execute(delete(AuditLog).where(AuditLog.at < cutoff))
    # `rowcount` is on CursorResult; `session.execute` is typed as the generic
    # Result, so cast at the one call site that needs it.
    rowcount = cast(CursorResult[Any], result).rowcount
    return rowcount if rowcount is not None else 0
