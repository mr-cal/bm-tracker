"""The append-only audit log.

Four rules, all enforced in `services/audit_service.py` and covered by tests:

1. Nothing updates or deletes a row.
2. `detail` is built from an allowlist and length-capped, so a note body, a
   password hash or a token cannot reach it.
3. `prev_hash` chains the rows, so modifying any earlier row breaks every hash
   after it. This is tamper *evidence*, not prevention — anyone with write
   access to the file can recompute the chain. It catches accident and casual
   editing, which is what an audit log for a handful of trusted friends is for.
4. Rows are pruned after a retention window, because an unbounded append-only
   table on a 10GB disk is a slow-motion disk-full.

There is deliberately no foreign key on `user_id`: a deleted user's entries must
survive the delete, and so must the record that they were deleted.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bm_tracker.models.base import Base, utcnow

MAX_ACTION_LENGTH = 64
MAX_ENTITY_TYPE_LENGTH = 32
MAX_ENTITY_ID_LENGTH = 64

# Rows older than this are dropped by a daily cron. 400 days comfortably covers
# "what happened last year" for a group this size.
RETENTION_DAYS = 400


class AuditLog(Base):
    """One recorded state change.

    `id` is autoincrement and never reused, so a gap-free sequence is itself
    evidence that nothing was deleted from the middle.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # The actor. NULL for anonymous or system actions.
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # e.g. "bm.create", "user.delete", "auth.login".
    action: Mapped[str] = mapped_column(
        String(MAX_ACTION_LENGTH), nullable=False, index=True
    )

    entity_type: Mapped[str | None] = mapped_column(
        String(MAX_ENTITY_TYPE_LENGTH), nullable=True
    )
    entity_id: Mapped[str | None] = mapped_column(
        String(MAX_ENTITY_ID_LENGTH), nullable=True
    )

    # JSON built from an allowlist of scalar keys. Never a whole object.
    detail: Mapped[str | None] = mapped_column(String, nullable=True)

    # SHA-256 of the previous row, or the genesis value for the first.
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (Index("ix_audit_log_at", "at"),)
