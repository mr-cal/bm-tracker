"""Achievement unlocks."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bm_tracker.models.base import Base, utcnow

if TYPE_CHECKING:
    from bm_tracker.models.user import User

MAX_KEY_LENGTH = 64


class AchievementUnlock(Base):
    """An achievement a user earned, in a given year.

    The year is part of the key, so achievements re-earn every January — a
    Perfect Week in 2026 is a different achievement from a Perfect Week in 2025.
    That is the same "fresh start" rule that bounds streaks, applied
    consistently. A lifetime key with a page-level year filter was rejected: an
    achievement earned in 2025 would sit permanently in that year's "locked"
    column with its progress bar reading 100%.

    `points` is copied on at unlock time, so raising an achievement's value
    later does not retroactively inflate anyone's history.

    This is the only stored component of the score. Logging points are derived
    (a backfill or an edit changes what a day was worth); an unlock is an event
    that happened once and cannot be un-happened.
    """

    __tablename__ = "achievement_unlocks"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    achievement_key: Mapped[str] = mapped_column(
        String(MAX_KEY_LENGTH), primary_key=True
    )
    year: Mapped[int] = mapped_column(Integer, primary_key=True)

    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # The cosine similarity that earned it, for the achievements that are found
    # by reading a note rather than counting one. Null for everything else:
    # there is no score for "you logged seven days running", because that is not
    # a judgement call.
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    user: Mapped[User] = relationship()
