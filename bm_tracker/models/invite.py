"""The one-time setup-link model."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bm_tracker.models.base import Base, utcnow

if TYPE_CHECKING:
    from bm_tracker.models.user import User

# A token is 32 bytes of `secrets.token_urlsafe`, so roughly 256 bits. At that
# entropy a fast hash is the right choice: a slow one protects nothing that an
# attacker with the hash could not already do, and would only slow redemption.
TOKEN_ENTROPY_BYTES = 32
DEFAULT_INVITE_TTL = timedelta(hours=72)


def hash_token(raw_token: str) -> str:
    """Return the stored form of a setup token.

    Only the hash is persisted, so a database dump yields nothing that can be
    redeemed.

    Args:
        raw_token: The token as generated and handed to the user.

    Returns:
        The hex SHA-256 digest to store.

    """
    return hashlib.sha256(raw_token.encode()).hexdigest()


class Invite(Base):
    """A single-use, expiring link that lets a new user set a password.

    An admin creates the account; this row is what turns it into something that
    can sign in. Reissuing simply adds another row — outstanding ones stay valid
    until used or expired, and the admin page can show which are live.
    """

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # SHA-256 of the token, never the token itself.
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    user: Mapped[User] = relationship(back_populates="invites")

    __table_args__ = (Index("ix_invites_user_unused", "user_id", "used_at"),)

    @classmethod
    def for_new_user(
        cls,
        *,
        user_id: int,
        token_hash: str,
        ttl: timedelta = DEFAULT_INVITE_TTL,
    ) -> Invite:
        """Build an unexpired, unused invite.

        Args:
            user_id: The account this invite provisions.
            token_hash: The stored form of the generated token.
            ttl: How long the link stays valid.

        Returns:
            An `Invite` ready to be added to a session.

        """
        return cls(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=utcnow() + ttl,
        )

    @property
    def is_redeemable(self) -> bool:
        """Return whether this invite can still set a password.

        Single-use and time-boxed. The token is compared by hash at redemption
        time, so a row is never mutated to mark redemption — `used_at` is set,
        and the check reads it.
        """
        return self.used_at is None and self.expires_at > utcnow()
