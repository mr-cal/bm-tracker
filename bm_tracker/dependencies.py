"""FastAPI dependency injection: sessions, the current user, and CSRF.

`is_active` and `session_version` are re-checked on **every** request rather
than only at sign-in. A session cookie is a bearer token that lives for 30 days,
so trusting what was in it at login means a deactivated user keeps access until
the cookie happens to expire, and a password change does not kill outstanding
cookies at all.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

from bm_tracker.models import User

# Session keys. `sv` is the user's session_version at the moment the cookie was
# issued; a mismatch means the account changed underneath it.
SESSION_USER_KEY = "uid"
SESSION_VERSION_KEY = "sv"
SESSION_CSRF_KEY = "csrf"

CSRF_FIELD_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session for the request.

    Args:
        request: The incoming request, used to reach the app's session factory.

    Yields:
        An `AsyncSession`, closed when the request finishes.

    """
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def csrf_token(request: Request) -> str:
    """Return this session's CSRF token, minting one if needed.

    Args:
        request: The incoming request.

    Returns:
        The session's CSRF token.

    """
    existing = request.session.get(SESSION_CSRF_KEY)
    if existing:
        return str(existing)
    minted = secrets.token_urlsafe(32)
    request.session[SESSION_CSRF_KEY] = minted
    return minted


def verify_csrf(request: Request, presented: str | None) -> None:
    """Raise unless the presented token matches the session's.

    `SameSite=Lax` alone is not sufficient for a multi-user app where an
    attacker has a reason to want somebody's session.

    Args:
        request: The incoming request.
        presented: The token from the form field or header.

    Raises:
        HTTPException: 403 when the token is missing or wrong.

    """
    expected = request.session.get(SESSION_CSRF_KEY)
    if (
        not expected
        or not presented
        or not secrets.compare_digest(str(expected), presented)
    ):
        msg = "Invalid or missing CSRF token."
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)


async def get_current_user(
    request: Request,
    session: DbSession,
) -> User | None:
    """Return the signed-in user, or `None`.

    Re-checks `is_active` and `session_version` on every call, so deactivation
    and a password change take effect on the next request rather than whenever
    the cookie happens to expire.

    Args:
        request: The incoming request.
        session: The database session.

    Returns:
        The current `User`, or `None` if there is no valid session.

    """
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None

    user = await session.get(User, int(user_id))
    if user is None or not user.is_active:
        return None

    if request.session.get(SESSION_VERSION_KEY) != user.session_version:
        return None

    return user


CurrentUser = Annotated[User | None, Depends(get_current_user)]


class LoginRequiredError(Exception):
    """Raised when a protected page is requested without a valid session.

    A dedicated exception rather than an `HTTPException` because the right
    answer for a browser following a link is a redirect, not a 401 carrying
    JSON. `create_app` installs `login_required_handler`.
    """


async def login_required_handler(request: Request, _exc: Exception) -> RedirectResponse:
    """Send an unauthenticated visitor to the sign-in page.

    Args:
        request: The incoming request.
        _exc: The exception that was raised.

    Returns:
        A redirect to `/login`.

    """
    del request
    return RedirectResponse("/login", status_code=303)


async def require_user(user: CurrentUser) -> User:
    """Return the current user, or ask them to sign in.

    Args:
        user: The current user, if any.

    Returns:
        The authenticated `User`.

    Raises:
        LoginRequiredError: When there is no valid session.

    """
    if user is None:
        raise LoginRequiredError
    return user


AuthenticatedUser = Annotated[User, Depends(require_user)]


async def require_admin(user: AuthenticatedUser) -> User:
    """Return the current user if they are an admin, or raise 403.

    Args:
        user: The authenticated user.

    Returns:
        The same `User`, when an admin.

    Raises:
        HTTPException: 403 when the user is not an admin.

    """
    if not user.is_admin:
        msg = "This page is for administrators."
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def sign_in(request: Request, user: User) -> None:
    """Establish a session for a user.

    The session version is recorded at this moment, so the cookie stops working
    the instant it is bumped.

    Args:
        request: The incoming request, whose session is written to.
        user: The user signing in.

    """
    request.session[SESSION_USER_KEY] = user.id
    request.session[SESSION_VERSION_KEY] = user.session_version
    request.session[SESSION_CSRF_KEY] = secrets.token_urlsafe(32)


def sign_out(request: Request) -> None:
    """Clear the session.

    Args:
        request: The incoming request.

    """
    request.session.clear()


def require_csrf() -> Callable[[Request], None]:
    """Return a dependency that rejects a request without a valid CSRF token.

    Starlette cannot read a form body in a dependency without consuming it, so
    the token is taken from the `X-CSRF-Token` header. The HTMX layer sends it
    on every state-changing request, which satisfies the check without needing
    the form body parsed twice.

    Returns:
        A dependency callable.

    """

    def _check(request: Request) -> None:
        verify_csrf(request, request.headers.get(CSRF_HEADER_NAME))

    return _check


CsrfGuard = Annotated[None, Depends(require_csrf())]
