"""Choosing what to say after you log something.

The concern this solves: if a message were picked at random, somebody who always
writes a note would only ever see the note lines, and somebody who never would
be stuck with a handful. So selection is **fair by construction** — within a
pool, the line shown fewest times wins, ties broken by longest unseen, so a
pool is cycled completely before any of its lines comes round twice. The pools
are large — sixty-odd lines in the general one — which means a regular logger
sees a different line almost every time, and a line is rare enough that reading
it still lands.

That needs a per-user count per line, which is what `celebration_seen` is for.
It is a row per (user, message) rather than a cursor, so the fairness property
survives a process restart and does not depend on insertion order.
"""

from __future__ import annotations

import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from bm_tracker.models import CelebrationSeen
from bm_tracker.models.base import utcnow

MESSAGES_PATH: Final = Path(__file__).parent / "messages.toml"

#: The pool for each kind of event. An event may ask for a specific pool, and
#: `log_any` is the one it asks for when nothing more specific happened — the
#: general pool, and the biggest one.
POOL_FOR_EVENT: Final[dict[str, str]] = {
    "log_any": "log_any",
    "log_none": "log_none",
    "quick_entry": "quick_entry",
    "note_added": "note_added",
    "backfill": "backfill",
    "streak": "streak",
}

#: The pool an event falls back to when it asks for one that does not exist. It
#: is `bouncy` rather than `log_any` so a typo in a new event name shows a line
#: instead of nothing, and so the blend below has a pool to blend with.
DEFAULT_POOL: Final = "bouncy"

#: The pool mixed into every event so a dedicated line does not make the app
#: feel mechanical. Fair rotation across the union means the blend pool's share
#: is its size over the total, so this is a weight rather than a probability:
#: `bouncy` at 28 lines against `log_any` at 66 is roughly a third of a plain
#: log, which is what a playful line in a serious app should amount to.
BLEND_POOL: Final = "bouncy"


class MessageError(ValueError):
    """Raised when the message catalogue is malformed."""


#: Form hints, grouped by slot. Filled in by `load`.
_VARIANTS_BY_SLOT: dict[str, tuple[Message, ...]] = {}


@dataclass(frozen=True, slots=True)
class Message:  # noqa: D101
    id: str
    pool: str
    text: str


def load(path: Path | None = None) -> dict[str, tuple[Message, ...]]:
    """Read the catalogue, grouped by pool.

    Args:
        path: An alternative catalogue file, for tests.

    Returns:
        A mapping of pool name to its messages, in file order.

    Raises:
        MessageError: If the catalogue is malformed or a pool is empty.

    """
    source = path or MESSAGES_PATH
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        msg = f"Message catalogue not found: {source}"
        raise MessageError(msg) from exc
    except tomllib.TOMLDecodeError as exc:
        msg = f"Message catalogue is not valid TOML: {exc}"
        raise MessageError(msg) from exc

    entries = data.get("message", [])
    if not isinstance(entries, list) or not entries:
        msg = "Message catalogue defines no messages"
        raise MessageError(msg)

    pools: dict[str, list[Message]] = defaultdict(list)
    for entry in entries:
        if not isinstance(entry, dict) or not {"id", "pool", "text"} <= set(entry):
            msg = f"Malformed message entry: {entry}"
            raise MessageError(msg)
        pools[str(entry["pool"])].append(
            Message(
                id=str(entry["id"]), pool=str(entry["pool"]), text=str(entry["text"])
            )
        )

    if not pools.get(DEFAULT_POOL):
        msg = f"Catalogue must define a {DEFAULT_POOL!r} pool as the fallback"
        raise MessageError(msg)

    variants: dict[str, list[Message]] = defaultdict(list)
    for entry in data.get("variant", []):
        if not isinstance(entry, dict) or not {"id", "slot", "text"} <= set(entry):
            msg = f"Malformed variant entry: {entry}"
            raise MessageError(msg)
        variants[str(entry["slot"])].append(
            Message(
                id=str(entry["id"]), pool=str(entry["slot"]), text=str(entry["text"])
            )
        )

    global _VARIANTS_BY_SLOT  # noqa: PLW0603 - the catalogue is loaded once
    _VARIANTS_BY_SLOT = {name: tuple(ms) for name, ms in variants.items()}
    return {name: tuple(messages) for name, messages in pools.items()}


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: Loaded once at import, alongside the achievement registry.
POOLS: Final[dict[str, tuple[Message, ...]]] = load()


async def variant(session: AsyncSession, user_id: int, slot: str) -> str:
    """Return a form hint for a slot, rotating fairly per person.

    The same rule as `pick`, for the same reason: a fixed string on a form you
    open several times a day stops being a hint. It borrows the celebration
    table rather than adding a second one, so there is one rotation to reason
    about.

    Args:
        session: The session to read and write through.
        user_id: Who the hint is for. The rotation is per user.
        slot: Which set of hints, e.g. "nothing_today".

    Returns:
        The chosen hint, or the slot name if the catalogue has none for it, so
        a missing entry shows something rather than nothing.

    """
    candidates = list(_VARIANTS_BY_SLOT.get(slot, ()))
    if not candidates:
        return slot.replace("_", " ")

    seen = {
        row.message_id: row
        for row in (
            await session.scalars(
                select(CelebrationSeen).where(
                    CelebrationSeen.user_id == user_id,
                    CelebrationSeen.message_id.in_([m.id for m in candidates]),
                )
            )
        ).all()
    }
    now = utcnow()
    chosen = min(
        candidates,
        key=lambda message: (
            seen[message.id].shown_count if message.id in seen else 0,
            seen[message.id].last_shown_at if message.id in seen else now,
            message.id,
        ),
    )

    row = seen.get(chosen.id)
    if row is None:
        session.add(
            CelebrationSeen(
                user_id=user_id, message_id=chosen.id, shown_count=1, last_shown_at=now
            )
        )
    else:
        row.shown_count += 1
        row.last_shown_at = now
    return chosen.text


async def pick(
    session: AsyncSession,
    user_id: int,
    event: str,
    *,
    blend: bool = True,
) -> str | None:
    """Return the line to show, or `None` when the catalogue is empty.

    Args:
        session: The session to read and write through.
        user_id: Who the message is for. The rotation is per user.
        event: What happened, e.g. "note_added".
        blend: Whether to sometimes use the general pool regardless.

    Returns:
        The chosen line, or `None`.

    """
    if not POOLS:
        return None

    pool_name = POOL_FOR_EVENT.get(event, DEFAULT_POOL)
    candidates = list(POOLS.get(pool_name, POOLS[DEFAULT_POOL]))
    if blend and candidates:
        candidates += list(POOLS.get(BLEND_POOL, ()))
    if not candidates:
        return None

    seen = {
        row.message_id: row
        for row in (
            await session.scalars(
                select(CelebrationSeen).where(
                    CelebrationSeen.user_id == user_id,
                    CelebrationSeen.message_id.in_([m.id for m in candidates]),
                )
            )
        ).all()
    }

    now = utcnow()
    # Fewest showings wins; ties go to whichever has been unseen longest.
    chosen = min(
        candidates,
        key=lambda message: (
            seen[message.id].shown_count if message.id in seen else 0,
            seen[message.id].last_shown_at if message.id in seen else now,
            message.id,
        ),
    )

    row = seen.get(chosen.id)
    if row is None:
        session.add(
            CelebrationSeen(
                user_id=user_id, message_id=chosen.id, shown_count=1, last_shown_at=now
            )
        )
    else:
        row.shown_count += 1
        row.last_shown_at = now
    return chosen.text


__all__ = [
    "DEFAULT_POOL",
    "POOL_FOR_EVENT",
    "POOLS",
    "Message",
    "MessageError",
    "load",
    "pick",
]
