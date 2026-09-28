"""Provisioning: admin creates an account, the user redeems a link to set a password."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bm_tracker import auth
from bm_tracker.models import Invite, User
from bm_tracker.models.base import utcnow

DEFAULT_TTL = timedelta(hours=72)


class InvalidInviteError(Exception):
    """Raised when a setup link cannot be redeemed."""


async def issue(
    session: AsyncSession, user: User, *, ttl: timedelta = DEFAULT_TTL
) -> tuple[Invite, str]:
    """Create a single-use setup link for a user.

    Reissuing simply adds a row — outstanding ones stay valid until used or
    expired, so a user who lost the first link is not locked out.

    Args:
        session: The session to write through.
        user: The account being provisioned.
        ttl: How long the link stays valid.

    Returns:
        The stored `Invite` and the raw token, which is returned exactly once
        and never persisted.

    """
    raw_token = auth.generate_token()
    invite = Invite.for_new_user(
        user_id=user.id,
        token_hash=auth.hash_token(raw_token),
        ttl=ttl,
    )
    session.add(invite)
    return invite, raw_token


async def find_valid(session: AsyncSession, raw_token: str) -> Invite:
    """Return the invite a token refers to, if it can still be redeemed.

    Args:
        session: The session to read through.
        raw_token: The token from the setup URL.

    Returns:
        The matching `Invite`.

    Raises:
        InvalidInviteError: If no live invite matches the token.

    """
    digest = auth.hash_token(raw_token)
    invite = await session.scalar(select(Invite).where(Invite.token_hash == digest))
    if invite is None or not invite.is_redeemable:
        msg = "That setup link is invalid or has expired."
        raise InvalidInviteError(msg)
    return invite


async def redeem(session: AsyncSession, raw_token: str, password: str) -> User:
    """Redeem a setup link, setting the account's password.

    The account can only be redeemed once: `used_at` is set here, and the
    lookup refuses a used invite, so a replayed link does nothing.

    Args:
        session: The session to write through.
        raw_token: The token from the setup URL.
        password: The password the user chose.

    Returns:
        The now-usable `User`.

    Raises:
        InvalidInviteError: If the link is not redeemable.
        ValueError: If the password fails the policy.

    """
    invite = await find_valid(session, raw_token)
    user = await session.get(User, invite.user_id)
    if user is None:
        msg = "That setup link is invalid or has expired."
        raise InvalidInviteError(msg)

    auth.check_password_policy(password, user.username)
    user.password_hash = auth.hash_password(password)
    # Bumping the version invalidates any cookie issued before this point.
    user.session_version += 1
    invite.used_at = utcnow()
    return user


async def live_invites(session: AsyncSession, user_id: int) -> list[Invite]:
    """Return a user's invites that have not been used and have not expired.

    Shown on the admin page so a stale link can be spotted before it is handed
    to somebody.

    Args:
        session: The session to read through.
        user_id: The account whose invites to list.

    Returns:
        The live `Invite` rows, newest first.

    """
    now = utcnow()
    rows = (
        await session.scalars(
            select(Invite)
            .where(
                Invite.user_id == user_id,
                Invite.used_at.is_(None),
                Invite.expires_at > now,
            )
            .order_by(Invite.created_at.desc())
        )
    ).all()
    return list(rows)


async def expire_stale(session: AsyncSession, *, before: datetime | None = None) -> int:
    """Mark unused, expired invites as used so they stop appearing as live.

    Args:
        session: The session to write through.
        before: The cut-off. Defaults to now.

    Returns:
        The number of invites expired.

    """
    cutoff = before or utcnow()
    rows = (
        await session.scalars(
            select(Invite).where(
                Invite.used_at.is_(None),
                Invite.expires_at <= cutoff,
            )
        )
    ).all()
    for row in rows:
        row.used_at = row.expires_at
    return len(rows)
