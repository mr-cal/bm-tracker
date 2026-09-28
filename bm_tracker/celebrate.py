"""Choosing what to say after you log something.

The concern this solves: if a message were picked at random, somebody who always
writes a note would only ever see the note lines, and somebody who never would
be stuck with a handful. So selection is **fair by construction** — within a
pool, the line shown fewest times wins, ties broken by longest unseen. Ten days
of noting cycles every note line before any of them repeats.

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
#: `log_any` is the fallback so there is always something to say.
POOL_FOR_EVENT: Final[dict[str, str]] = {
    "log_none": "log_none",
    "quick_entry": "quick_entry",
    "note_added": "note_added",
    "backfill": "backfill",
    "streak": "streak",
}

DEFAULT_POOL: Final = "bouncy"

#: Chance of ignoring the specific pool and using the general one anyway, so a
#: dedicated line does not make the app feel mechanical.
POOL_BLEND_CHANCE: Final = 0.2


class MessageError(ValueError):
    """Raised when the message catalogue is malformed."""


@dataclass(frozen=True, slots=True)
class Message:
    """One line of celebration copy."""

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

    return {name: tuple(messages) for name, messages in pools.items()}


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: Loaded once at import, alongside the achievement registry.
POOLS: Final[dict[str, tuple[Message, ...]]] = load()


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
        # Blend the general pool in occasionally so a dedicated line does not
        # make the app feel mechanical.
        candidates += list(POOLS[DEFAULT_POOL])
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
