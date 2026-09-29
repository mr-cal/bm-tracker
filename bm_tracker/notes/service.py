"""Turning a note into an achievement, and keeping it that way.

The whole subsystem is off unless `EMBEDDING_API_KEY` is set, which is the
normal case for a private install. Nothing here is on the critical path of a
log: a note is saved whether or not this succeeds, and a provider that is down
or out of credit means one fewer unlock rather than a lost entry.

Note achievements share the `achievement_unlocks` table under a `note:` prefix
rather than living in a table of their own, which is what makes them appear on
the achievements page and count on the leaderboard for nothing. `rebuild` only
ever adds rows, so a namespace it does not know about survives it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from bm_tracker.models import AchievementUnlock
from bm_tracker.notes.embeddings import EmbeddingError, OpenRouterEmbedder
from bm_tracker.notes.match import Match, Matcher
from bm_tracker.timezones import now_in

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from bm_tracker.models import User
    from bm_tracker.notes.achievements import NoteAchievement
    from bm_tracker.settings import Settings

logger = logging.getLogger(__name__)

#: The namespace that keeps a note achievement from colliding with a counted one,
#: and tells the achievements page which is which.
PREFIX: Final = "note:"

DEFAULT_CACHE_PATH: Final = Path("data/note_prototypes.json")

__all__ = [
    "DEFAULT_CACHE_PATH",
    "Match",
    "PREFIX",
    "earned_keys",
    "is_note_key",
    "key_for",
    "matcher_from",
    "try_match",
]


def key_for(achievement: NoteAchievement) -> str:
    """Return the unlock key for a note achievement.

    Args:
        achievement: The definition.

    Returns:
        The namespaced key.

    """
    return f"{PREFIX}{achievement.key}"


def is_note_key(key: str) -> bool:
    """Return whether an unlock key came from a note.

    Args:
        key: The unlock key.

    Returns:
        Whether it is in the note namespace.

    """
    return key.startswith(PREFIX)


def matcher_from(
    settings: Settings, *, cache_path: Path | None = None
) -> Matcher | None:
    """Build a matcher, or None when there is no key.

    Args:
        settings: The app settings.
        cache_path: Where to cache prototype vectors.

    Returns:
        A matcher, or None when note achievements are switched off.

    """
    if not settings.embedding_api_key.strip():
        return None
    embedder = OpenRouterEmbedder(
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        api_key=settings.embedding_api_key,
        dimensions=settings.embedding_dimensions,
    )
    return Matcher(embedder=embedder, cache_path=cache_path or DEFAULT_CACHE_PATH)


async def earned_keys(session: AsyncSession, user_id: int, year: int) -> set[str]:
    """Return the note achievements somebody has already earned this year.

    Args:
        session: The session to read through.
        user_id: Whose record to check.
        year: The calendar year.

    Returns:
        The bare keys, un-namespaced, so a match can be tested against them.

    """
    rows = (
        await session.scalars(
            select(AchievementUnlock.achievement_key).where(
                AchievementUnlock.user_id == user_id,
                AchievementUnlock.year == year,
            )
        )
    ).all()
    prefix = PREFIX
    return {key[len(prefix) :] for key in rows if key.startswith(prefix)}


async def try_match(
    session: AsyncSession,
    settings: Settings,
    user: User,
    text: str | None,
    *,
    cache_path: Path | None = None,
) -> list[Match]:
    """Match a note and record anything new it earns.

    Never raises. A note is the job; the unlock is the treat, and a provider
    having a bad day must not cost somebody their log.

    Args:
        session: The session to read and write through.
        settings: The app settings.
        user: Who wrote the note.
        text: The note, or None.
        cache_path: Where to cache prototype vectors.

    Returns:
        What the note earned, which is usually nothing.

    """
    if not text or not text.strip():
        return []
    matcher = matcher_from(settings, cache_path=cache_path)
    if matcher is None:
        return []

    local_today, _ = now_in(user.timezone)
    year = local_today.year
    already = await earned_keys(session, user.id, year)

    try:
        found = await matcher.match(text)
    except EmbeddingError as exc:
        logger.warning("Note achievement matching failed: %s", exc)
        return []

    for match in found:
        if match.key in already:
            continue
        already.add(match.key)
        session.add(
            AchievementUnlock(
                user_id=user.id,
                achievement_key=f"{PREFIX}{match.key}",
                year=year,
                points=match.points,
                score=match.score,
            )
        )
    return found
