"""Derived per-user facts, the input to achievement evaluation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bm_tracker.models.base import Base

if TYPE_CHECKING:
    from bm_tracker.models.user import User

MAX_FACT_KEY_LENGTH = 64


class UserFact(Base):
    """One derived scalar about a user, e.g. `bm_count_total`.

    A key/value table rather than columns, so that an achievement needing a new
    fact is not a migration. Around twenty of these exist; evaluating 300
    achievements against twenty floats is a few hundred integer comparisons,
    which is why the engine never re-scans history.
    """

    __tablename__ = "user_facts"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    fact_key: Mapped[str] = mapped_column(String(MAX_FACT_KEY_LENGTH), primary_key=True)
    fact_value: Mapped[float] = mapped_column(Float, nullable=False)

    user: Mapped[User] = relationship()
