"""How often each celebration line has been shown to each user.

Per (user, message) rather than a single cursor, so the fairness property
survives a process restart and does not depend on insertion order: the line with
the fewest showings wins, ties broken by longest unseen.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bm_tracker.models.base import Base, utcnow

MAX_MESSAGE_ID_LENGTH = 64


class CelebrationSeen(Base):
    """One message's showing count for one user."""

    __tablename__ = "celebration_seen"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    message_id: Mapped[str] = mapped_column(
        String(MAX_MESSAGE_ID_LENGTH), primary_key=True
    )
    shown_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_shown_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
