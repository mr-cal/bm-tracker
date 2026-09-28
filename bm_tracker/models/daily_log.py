"""The daily log: the aggregate root of the whole app."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bm_tracker.models.base import Base, utcnow

if TYPE_CHECKING:
    from bm_tracker.models.bm_entry import BmEntry
    from bm_tracker.models.user import User


class DailyLog(Base):
    """One calendar day for one user.

    The row's existence is the definition of "this day is logged", which is what
    makes a "nothing today" day distinguishable from a day nobody opened the app
    for. `n_bms = 0` is a real, scored, streak-extending state.

    `day` and `logged_at` are deliberately separate. `day` is when the BMs
    happened; `logged_at` is when the user recorded it. They differ only on a
    backfill, and that difference is the entire basis of the scoring rules.
    """

    __tablename__ = "daily_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # The occurrence date, already resolved in the user's own timezone. Storing
    # a resolved date rather than a UTC instant means a later timezone change
    # cannot shift a user's history across day boundaries.
    day: Mapped[date] = mapped_column(Date, nullable=False)

    # Denormalised count of bm_entries, so the dashboard and the BMs-per-day
    # average do not need a correlated COUNT. Maintained in the same
    # transaction as the entry writes, and asserted against COUNT(*) in tests.
    n_bms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # A note written against the day. Live only when n_bms is 0; see
    # `is_note_live`. There is no flag column and no CHECK constraint: whether
    # the note is live is derived from n_bms, so adding the first BM supersedes
    # it by arithmetic and deleting the last BM revives it, with nothing written
    # either way and nothing that can fall out of step.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # When the row was first written.
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    # When the user recorded it. Differs from `day` on a backfill.
    logged_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    user: Mapped[User] = relationship(back_populates="daily_logs")
    entries: Mapped[list[BmEntry]] = relationship(
        back_populates="daily_log",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # One row per user per day. This is the constraint that makes "a day is
        # logged" a single fact rather than a tally.
        UniqueConstraint("user_id", "day", name="uq_daily_logs_user_day"),
        CheckConstraint("n_bms >= 0", name="ck_daily_logs_n_bms_non_negative"),
        Index("ix_daily_logs_user_day", "user_id", "day"),
    )

    @property
    def is_note_live(self) -> bool:
        """Return whether the day-level note currently counts and is shown.

        A day-note is live exactly when the day is empty. Once a BM exists the
        day is described by its entries, and the note is retained as
        superseded — visible to its owner, scored by nobody.
        """
        return bool(self.notes and self.notes.strip() and self.n_bms == 0)

    @property
    def is_superseded(self) -> bool:
        """Return whether a written day-note has been overtaken by a BM."""
        return bool(self.notes and self.notes.strip() and self.n_bms > 0)
