"""A single bowel movement."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bm_tracker.models.base import Base, utcnow

if TYPE_CHECKING:
    from bm_tracker.models.daily_log import DailyLog

# The Bristol stool scale. 1-2 hard, 3-4 normal, 5-6 soft, 7 liquid.
BRISTOL_MIN = 1
BRISTOL_MAX = 7

# How hard it was to pass. 1 easy, 2 some effort, 3 hard.
STRAIN_MIN = 1
STRAIN_MAX = 3


class BmEntry(Base):
    """One bowel movement, belonging to a day.

    `occurred_local` is naive wall-clock time exactly as the user typed it, and
    is never converted. Converting it would mean that changing a timezone later
    reinterpreted past entries, which for a "what time did I go" log is simply
    wrong. The cost is losing cross-timezone ordering, which nothing needs.

    `created_at` is when the row was written, and is what the ten-minute bonus
    is measured against.

    The optional fields are `spicy`, `urgent` and `strain`. Urgency is a
    boolean the user ticks, not a derivation from the logging delay. The Bristol
    descriptor flags were specified and then dropped: the log form is a phone
    form used in a hurry, and every extra tap is a reason not to open the app at
    all — which is the one thing the whole design is trying to encourage.
    """

    __tablename__ = "bm_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_log_id: Mapped[int] = mapped_column(
        ForeignKey("daily_logs.id", ondelete="CASCADE"), nullable=False
    )

    # Wall clock as typed, in the owner's timezone. Not UTC, not converted.
    occurred_local: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    bristol_type: Mapped[int] = mapped_column(Integer, nullable=False)

    # Whether this followed spicy food. One boolean rather than a tag system,
    # because it is the only tag.
    spicy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Whether it was urgent — a call that could not wait. A boolean like
    # `spicy`, not derived: how long it took to write the entry down is a
    # property of the logging, and conflating the two made a column claim
    # something about the BM that the BM does not know.
    urgent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # How hard it was to pass, 1-3. Nullable because it is optional on the form:
    # a null means "not recorded", which is not the same claim as "was easy".
    strain: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # A note attached to this specific BM. Always live, unlike a day-note.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    daily_log: Mapped[DailyLog] = relationship(back_populates="entries")

    __table_args__ = (
        CheckConstraint(
            f"bristol_type BETWEEN {BRISTOL_MIN} AND {BRISTOL_MAX}",
            name="ck_bm_entries_bristol_type_range",
        ),
        CheckConstraint(
            f"strain IS NULL OR strain BETWEEN {STRAIN_MIN} AND {STRAIN_MAX}",
            name="ck_bm_entries_strain_range",
        ),
        Index("ix_bm_entries_daily_log", "daily_log_id"),
    )

    @property
    def has_note(self) -> bool:
        """Return whether this entry carries a note that pays.

        Whitespace-only notes do not count: a stray space is not a diary entry.
        """
        return bool(self.notes and self.notes.strip())

    @property
    def entry_delay_seconds(self) -> float:
        """Return the seconds between the stated occurrence and the write.

        Negative when the user typed a time slightly ahead of the clock, which
        the quick-entry bonus treats as "close enough" by absolute difference.
        """
        return (self.created_at - self.occurred_local).total_seconds()
