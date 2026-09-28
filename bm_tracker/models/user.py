"""The user account model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bm_tracker.models.base import Base, utcnow

if TYPE_CHECKING:
    from bm_tracker.models.daily_log import DailyLog
    from bm_tracker.models.invite import Invite

# A password hash is null until the account has redeemed its setup link. An
# account in that state exists and is administrable but cannot authenticate.
MIN_USERNAME_LENGTH = 1
MAX_USERNAME_LENGTH = 40
MAX_DISPLAY_NAME_LENGTH = 60


class User(Base):
    """A person who can log in.

    Accounts are created by an admin, never self-registered.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # A slug, shown to other users in place of a real name. Unique so that
    # /people/{username} is unambiguous.
    username: Mapped[str] = mapped_column(
        String(MAX_USERNAME_LENGTH), unique=True, nullable=False, index=True
    )

    display_name: Mapped[str] = mapped_column(
        String(MAX_DISPLAY_NAME_LENGTH), nullable=False
    )

    # argon2id, or NULL until the setup link is redeemed.
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Bumped to invalidate every outstanding session cookie for this user. A
    # password change, a deactivation and a promotion each bump it, so a stolen
    # cookie dies the moment the thing behind it changes rather than lasting the
    # full rolling expiry.
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # An IANA name, e.g. "Europe/London". Decides where a day's boundary falls.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    invites: Mapped[list[Invite]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    daily_logs: Mapped[list[DailyLog]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def can_authenticate(self) -> bool:
        """Return whether this account could complete a login.

        A provisioned-but-never-redeemed account is a valid state, and an
        inactive one is a valid state. Neither may sign in.
        """
        return bool(self.is_active and self.password_hash)
