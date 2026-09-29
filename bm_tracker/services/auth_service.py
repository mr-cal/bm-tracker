"""Sign-in, password changes and account administration."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bm_tracker import auth
from bm_tracker.models import User
from bm_tracker.timezones import DEFAULT_TIMEZONE

# Two dimensions, because either alone is insufficient. Per-IP does nothing
# against a slow spray across many usernames from many hosts; per-account does
# nothing against a shared network where everyone is behind one address.
IP_ATTEMPTS_PER_WINDOW: Final = 5
IP_WINDOW_SECONDS: Final = 60

ACCOUNT_ATTEMPTS_PER_WINDOW: Final = 10
ACCOUNT_WINDOW_SECONDS: Final = 15 * 60

LOCKOUT_SECONDS: Final = 15 * 60

# A dummy hash verified against when no user matches, so that a request for a
# nonexistent username costs the same time as one for a real account. Without
# it, response time alone enumerates who has an account.
_DUMMY_HASH: Final = (
    "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHRzb21lc2FsdA$"
    "0Q0h1s0mQ0h1s0mQ0h1s0mQ0h1s0mQ0h1s0mQ0h1s0mQ0h1s0mQ0h1s0mQ0h1s0mQ0h1s0"
)


class AuthenticationError(Exception):
    """Raised when a sign-in attempt is refused."""


@dataclass
class Throttle:
    """An in-process failure counter for sign-in attempts.

    The app runs a single worker on purpose (SQLite serialises writers), so
    process memory is the whole story and a shared store would be ceremony. If
    the app ever runs more than one worker, this must move to the database or a
    cache, or half the attempts will not count.
    """

    _attempts: dict[str, list[float]] = field(default_factory=dict)

    def _prune(self, key: str, window: int) -> list[float]:
        """Drop timestamps outside the window and return what remains.

        Args:
            key: The bucket to prune.
            window: The window length in seconds.

        Returns:
            The attempt timestamps still inside the window.

        """
        cutoff = time.monotonic() - window
        recent = [stamp for stamp in self._attempts.get(key, []) if stamp > cutoff]
        if recent:
            self._attempts[key] = recent
        else:
            self._attempts.pop(key, None)
        return recent

    def is_locked(self, key: str, *, limit: int, window: int) -> bool:
        """Return whether a bucket is currently locked out.

        Args:
            key: The bucket to check.
            limit: Attempts allowed in the window.
            window: The window length in seconds.

        Returns:
            Whether further attempts should be refused.

        """
        return len(self._prune(key, window)) >= limit

    def record_failure(self, key: str, *, window: int) -> None:
        """Record a failed attempt.

        Args:
            key: The bucket to record against.
            window: The window length in seconds.

        """
        self._attempts.setdefault(key, []).append(time.monotonic())
        self._prune(key, window)

    def clear(self, key: str) -> None:
        """Forget a bucket, on a successful sign-in.

        Args:
            key: The bucket to clear.

        """
        self._attempts.pop(key, None)

    def reset(self) -> None:
        """Forget every bucket. Used by tests."""
        self._attempts.clear()


# The process-wide throttle. One instance for the whole app.
throttle = Throttle()


def _account_key(username: str) -> str:
    return f"account:{username.strip().lower()}"


def _ip_key(ip: str) -> str:
    return f"ip:{ip}"


async def authenticate(
    session: AsyncSession,
    username: str,
    password: str,
    *,
    client_ip: str = "",
) -> User:
    """Verify a username and password, enforcing both throttle dimensions.

    Args:
        session: The session to read through.
        username: The username as typed.
        password: The password as typed.
        client_ip: The caller's address, for the per-IP bucket.

    Returns:
        The authenticated `User`.

    Raises:
        AuthenticationError: If the throttle is engaged, the account is
            unknown, inactive, unprovisioned, or the password is wrong. All four
            are the same message, so the response does not say which.

    """
    account = _account_key(username)
    ip = _ip_key(client_ip or "unknown")

    if throttle.is_locked(
        account, limit=ACCOUNT_ATTEMPTS_PER_WINDOW, window=ACCOUNT_WINDOW_SECONDS
    ):
        msg = "Too many failed attempts. Try again later."
        raise AuthenticationError(msg)
    if throttle.is_locked(ip, limit=IP_ATTEMPTS_PER_WINDOW, window=IP_WINDOW_SECONDS):
        msg = "Too many failed attempts. Try again later."
        raise AuthenticationError(msg)

    user = await session.scalar(
        select(User).where(User.username == username.strip().lower())
    )

    if user is None:
        # Spend the same time verifying a throwaway hash, so that an unknown
        # username is not distinguishable by how quickly it fails.
        auth.verify_password(password, _DUMMY_HASH)
        throttle.record_failure(account, window=ACCOUNT_WINDOW_SECONDS)
        throttle.record_failure(ip, window=IP_WINDOW_SECONDS)
        msg = "Incorrect username or password."
        raise AuthenticationError(msg)

    if not user.is_active or not auth.verify_password(
        password, user.password_hash or ""
    ):
        throttle.record_failure(account, window=ACCOUNT_WINDOW_SECONDS)
        throttle.record_failure(ip, window=IP_WINDOW_SECONDS)
        msg = "Incorrect username or password."
        raise AuthenticationError(msg)

    if auth.needs_rehash(user.password_hash or ""):
        user.password_hash = auth.hash_password(password)
        user.session_version += 1

    throttle.clear(account)
    throttle.clear(ip)
    return user


def change_password(user: User, current_password: str, new_password: str) -> None:
    """Change a user's own password.

    Bumps the session version, which invalidates every outstanding cookie
    anywhere — including a stolen one.

    Synchronous, deliberately: it performs no I/O, only hashing and field
    mutation, and the caller owns the transaction. An `async def` here would be
    a coroutine that silently does nothing when awaited by nobody.

    Args:
        user: The user changing their password. Must be attached to a session
            the caller will commit.
        current_password: The existing password, to prove possession.
        new_password: The replacement.

    Raises:
        AuthenticationError: If the current password is wrong.
        ValueError: If the new password fails the policy.

    """
    if not auth.verify_password(current_password, user.password_hash or ""):
        msg = "Your current password is incorrect."
        raise AuthenticationError(msg)
    auth.check_password_policy(new_password, user.username)
    user.password_hash = auth.hash_password(new_password)
    user.session_version += 1


def invalidate_sessions(user: User) -> None:
    """Bump the session version, killing every outstanding cookie.

    Used for deactivation, promotion and demotion, as well as password
    changes.

    Args:
        user: The user whose sessions should die.

    """
    user.session_version += 1


async def create_user(
    session: AsyncSession,
    username: str,
    display_name: str,
    *,
    is_admin: bool = False,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> User:
    """Create a provisioned-but-unusable account.

    `password_hash` stays null until the setup link is redeemed, which is how
    the app knows an account exists but cannot yet sign in.

    Args:
        session: The session to write through.
        username: The slug shown to other users.
        display_name: The name shown in the interface.
        is_admin: Whether the account gets admin rights.
        timezone_name: An IANA timezone.

    Returns:
        The created `User`.

    Raises:
        ValueError: If the username is already taken.

    """
    slug = username.strip().lower()
    existing = await session.scalar(select(User).where(User.username == slug))
    if existing is not None:
        msg = f"The username {slug!r} is already taken."
        raise ValueError(msg)

    user = User(
        username=slug,
        display_name=display_name.strip() or slug,
        is_admin=is_admin,
        timezone=timezone_name,
    )
    session.add(user)
    await session.flush()
    return user
