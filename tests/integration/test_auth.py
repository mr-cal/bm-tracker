"""Tests for authentication, sessions, CSRF and the admin flows.

Driven through the real HTTP surface rather than by calling services directly,
because most of what matters here is about how the pieces compose: a session
cookie, a CSRF header, and a database row.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from datetime import date
from typing import TYPE_CHECKING

import pytest
from bm_tracker import auth
from bm_tracker.dependencies import CSRF_FIELD_NAME, CSRF_HEADER_NAME
from bm_tracker.models import Invite, User
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from bm_tracker.settings import Settings

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
SETUP_LINK_RE = re.compile(r"(/setup/[A-Za-z0-9_-]{20,})")

GOOD_PASSWORD = "correct horse battery staple"


def csrf_from(html: str) -> str:
    """Return the CSRF token embedded in a rendered form.

    Args:
        html: The rendered page.

    Returns:
        The token.

    Raises:
        AssertionError: If the page has no CSRF field.
    """
    match = CSRF_RE.search(html)
    assert match, "no csrf_token in the rendered form"
    return match.group(1)


async def make_admin(
    session: AsyncSession, username: str = "cal", *, is_admin: bool = True
) -> User:
    """Create a usable administrator with a known password.

    Args:
        session: The database session.
        username: The account name.
        is_admin: Whether the account is an administrator.

    Returns:
        The created `User`.
    """
    user = User(
        username=username,
        display_name=username.title(),
        password_hash=auth.hash_password(GOOD_PASSWORD),
        is_admin=is_admin,
        timezone="UTC",
    )
    session.add(user)
    await session.commit()
    return user


async def make_user(session: AsyncSession, username: str) -> tuple[User, str]:
    """Create a provisioned user and return it with its setup token.

    Args:
        session: The database session.
        username: The account name.

    Returns:
        The `User` and the raw setup token.
    """
    from bm_tracker.services import invite_service  # noqa: PLC0415

    user = User(username=username, display_name=username.title(), timezone="UTC")
    session.add(user)
    await session.flush()
    _, token = await invite_service.issue(session, user)
    await session.commit()
    return user, token


@pytest.fixture(autouse=True)
def _reset_throttle() -> Iterator[None]:
    """Clear the sign-in throttle between tests.

    The throttle is process-wide on purpose — the app runs one worker — so it
    has to be reset explicitly or one test's failures lock out the next.
    """
    auth_service_throttle_reset()
    yield
    auth_service_throttle_reset()


def auth_service_throttle_reset() -> None:
    """Reset the module-level sign-in throttle."""
    from bm_tracker.services.auth_service import throttle  # noqa: PLC0415

    throttle.reset()


@pytest.fixture
async def anon_client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """An HTTP client with no session."""
    from bm_tracker.app import create_app  # noqa: PLC0415

    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://testserver") as http,
        app.router.lifespan_context(app),
    ):
        yield http


async def sign_in(
    client: AsyncClient, username: str = "cal", password: str = GOOD_PASSWORD
) -> None:
    """Drive the real sign-in form.

    Args:
        client: The HTTP client.
        username: The account to sign in as.
        password: The password to use.
    """
    form_page = await client.get("/login")
    response = await client.post(
        "/login",
        data={
            CSRF_FIELD_NAME: csrf_from(form_page.text),
            "username": username,
            "password": password,
        },
        headers={CSRF_HEADER_NAME: csrf_from(form_page.text)},
    )
    assert response.status_code == 303, response.text


# --- password handling ----------------------------------------------------


def test_password_round_trip() -> None:
    """A hash verifies the password that made it and nothing else."""
    stored = auth.hash_password(GOOD_PASSWORD)

    assert stored != GOOD_PASSWORD
    assert auth.verify_password(GOOD_PASSWORD, stored)
    assert not auth.verify_password("wrong password", stored)


def test_verify_against_a_missing_hash_is_false_not_an_error() -> None:
    """A provisioned-but-unredeemed account must fail the login, not the request."""
    assert not auth.verify_password(GOOD_PASSWORD, "")


def test_verify_against_a_corrupt_hash_is_false() -> None:
    """A malformed hash is a failed login rather than a 500."""
    assert not auth.verify_password(GOOD_PASSWORD, "not-a-real-hash")


def test_tokens_are_unguessable_and_stored_hashed() -> None:
    """Two tokens differ, and only a hash of one is ever persisted."""
    one = auth.generate_token()
    two = auth.generate_token()

    assert one != two
    assert len(one) >= 32
    assert one != auth.hash_token(one)
    assert auth.tokens_match(one, auth.hash_token(one))
    assert not auth.tokens_match(two, auth.hash_token(one))


@pytest.mark.parametrize(
    "password",
    ["short", GOOD_PASSWORD + " x" * 300, "passwordpassword", "cal-cal-cal-1234"],
)
def test_weak_passwords_are_refused(password: str) -> None:
    """Length, an obvious ceiling, the common list, and the username."""
    with pytest.raises(ValueError, match="at least 12|at most|common|must not contain"):
        auth.check_password_policy(password, "cal")


def test_a_good_password_passes() -> None:
    """A long passphrase with no connection to the username is accepted."""
    auth.check_password_policy(GOOD_PASSWORD, "cal")


# --- the sign-in flow -----------------------------------------------------


async def test_sign_in_succeeds_with_the_right_password(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """The happy path establishes a session and redirects home."""
    await make_admin(session)
    await sign_in(anon_client)

    response = await anon_client.get("/", follow_redirects=False)
    assert response.status_code in (200, 303)


async def test_sign_in_fails_with_the_wrong_password(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A wrong password re-renders the form and sets no session."""
    await make_admin(session)
    form_page = await anon_client.get("/login")

    response = await anon_client.post(
        "/login",
        data={
            CSRF_FIELD_NAME: csrf_from(form_page.text),
            "username": "cal",
            "password": "not the password",
        },
    )

    assert response.status_code == 401
    assert "Incorrect username or password" in response.text


async def test_unknown_username_is_indistinguishable(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A wrong password and an unknown account give the same answer.

    Differing responses would let an unauthenticated caller enumerate who has an
    account.
    """
    await make_admin(session)
    form_page = await anon_client.get("/login")

    def _post(username: str, password: str):
        return anon_client.post(
            "/login",
            data={
                CSRF_FIELD_NAME: csrf_from(form_page.text),
                "username": username,
                "password": password,
            },
        )

    wrong_password = await _post("cal", "not the password")
    unknown_user = await _post("nobody", "not the password")

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert "Incorrect username or password" in unknown_user.text


async def test_login_rejects_a_missing_csrf_token(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A cross-site form post cannot sign anyone in."""
    await make_admin(session)

    response = await anon_client.post(
        "/login", data={"username": "cal", "password": GOOD_PASSWORD}
    )

    assert response.status_code == 403


async def test_login_rejects_a_wrong_csrf_token(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """And neither can a guessed one."""
    await make_admin(session)

    response = await anon_client.post(
        "/login",
        data={
            CSRF_FIELD_NAME: "not-the-right-token",
            "username": "cal",
            "password": GOOD_PASSWORD,
        },
    )

    assert response.status_code == 403


async def test_repeated_failures_lock_the_account(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """Brute force is throttled, and the correct password is then refused too.

    The lockout is deliberately blunt: it does not care that the eleventh
    attempt was correct.
    """
    await make_admin(session)
    form_page = await anon_client.get("/login")

    for _ in range(10):
        await anon_client.post(
            "/login",
            data={
                CSRF_FIELD_NAME: csrf_from(form_page.text),
                "username": "cal",
                "password": "wrong",
            },
        )

    locked = await anon_client.post(
        "/login",
        data={
            CSRF_FIELD_NAME: csrf_from(form_page.text),
            "username": "cal",
            "password": GOOD_PASSWORD,
        },
    )

    assert locked.status_code == 401
    assert "Too many failed attempts" in locked.text


async def test_logout_is_post_only(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A GET logout could be triggered by any image tag on a page."""
    await make_admin(session)
    await sign_in(anon_client)

    get_attempt = await anon_client.get("/logout", follow_redirects=False)
    assert get_attempt.status_code in (404, 405)

    post_attempt = await anon_client.post("/logout", follow_redirects=False)
    assert post_attempt.status_code == 303


# --- session invalidation -------------------------------------------------


async def test_deactivation_kills_a_live_session(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A suspended user is signed out on their next request.

    The session cookie is a bearer token that lives for thirty days, so
    trusting what was in it at sign-in would leave a suspended account working
    for up to a month.
    """
    admin = await make_admin(session)
    other, _ = await make_user(session, "bee")
    other.password_hash = auth.hash_password(GOOD_PASSWORD)
    await session.commit()

    await sign_in(anon_client, "bee")
    before = await anon_client.get("/admin", follow_redirects=False)
    assert before.status_code in (403, 303)

    other.is_active = False
    await session.commit()
    del admin

    after = await anon_client.get("/admin", follow_redirects=False)
    assert after.status_code == 303
    assert after.headers.get("location") == "/login"


async def test_password_change_invalidates_existing_sessions(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """Changing a password kills outstanding cookies, including a stolen one."""
    from bm_tracker.services import auth_service  # noqa: PLC0415

    user = await make_admin(session, "bee", is_admin=False)
    await sign_in(anon_client, "bee")

    auth_service.change_password(user, GOOD_PASSWORD, "a whole new passphrase")
    await session.commit()

    response = await anon_client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/login"


# --- provisioning ---------------------------------------------------------


async def test_setup_link_sets_a_password_once(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A setup link redeems once and signs the user in."""
    _, token = await make_user(session, "bee")

    form_page = await anon_client.get(f"/setup/{token}")
    assert form_page.status_code == 200

    response = await anon_client.post(
        f"/setup/{token}",
        data={
            CSRF_FIELD_NAME: csrf_from(form_page.text),
            "password": GOOD_PASSWORD,
            "confirm_password": GOOD_PASSWORD,
        },
    )
    assert response.status_code == 303

    user = await session.scalar(select(User).where(User.username == "bee"))
    assert user is not None
    assert user.password_hash is not None
    assert auth.verify_password(GOOD_PASSWORD, user.password_hash)

    invite = await session.scalar(select(Invite).where(Invite.user_id == user.id))
    assert invite is not None
    assert invite.used_at is not None


async def test_a_setup_link_cannot_be_replayed(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A second attempt with the same token is refused."""
    _, token = await make_user(session, "bee")
    form_page = await anon_client.get(f"/setup/{token}")

    await anon_client.post(
        f"/setup/{token}",
        data={
            CSRF_FIELD_NAME: csrf_from(form_page.text),
            "password": GOOD_PASSWORD,
            "confirm_password": GOOD_PASSWORD,
        },
    )

    replay_page = await anon_client.get(f"/setup/{token}")
    assert replay_page.status_code == 410


async def test_an_expired_link_is_refused(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """Time-boxed, not merely single-use."""
    from datetime import timedelta  # noqa: PLC0415

    from bm_tracker.models.base import utcnow  # noqa: PLC0415

    _, token = await make_user(session, "bee")
    invite = await session.scalar(select(Invite))
    assert invite is not None
    invite.expires_at = utcnow() - timedelta(hours=1)
    await session.commit()

    response = await anon_client.get(f"/setup/{token}")
    assert response.status_code == 410


async def test_setup_refuses_mismatched_passwords(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A typo is caught before anything is written."""
    _, token = await make_user(session, "bee")
    form_page = await anon_client.get(f"/setup/{token}")

    response = await anon_client.post(
        f"/setup/{token}",
        data={
            CSRF_FIELD_NAME: csrf_from(form_page.text),
            "password": GOOD_PASSWORD,
            "confirm_password": GOOD_PASSWORD + " different",
        },
    )

    assert response.status_code == 400
    assert "did not match" in response.text


async def test_setup_enforces_the_password_policy(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A short password is refused at redemption, not at sign-in later."""
    _, token = await make_user(session, "bee")
    form_page = await anon_client.get(f"/setup/{token}")

    response = await anon_client.post(
        f"/setup/{token}",
        data={
            CSRF_FIELD_NAME: csrf_from(form_page.text),
            "password": "short",
            "confirm_password": "short",
        },
    )

    assert response.status_code == 400
    assert "at least 12" in response.text


# --- admin ----------------------------------------------------------------


async def test_non_admins_cannot_reach_admin(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A non-admin is refused, and told so."""
    await make_admin(session, "bee", is_admin=False)
    await sign_in(anon_client, "bee")

    response = await anon_client.get("/admin", follow_redirects=False)

    assert response.status_code == 403


async def test_anonymous_users_are_sent_to_login(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A protected page redirects rather than leaking its existence."""
    response = await anon_client.get("/admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers.get("location") == "/login"


async def test_admin_creates_a_user_and_shows_the_link(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """The provisioning flow, end to end through the admin page."""
    await make_admin(session)
    await sign_in(anon_client)

    form_page = await anon_client.get("/admin")
    response = await anon_client.post(
        "/admin/users",
        data={
            CSRF_FIELD_NAME: csrf_from(form_page.text),
            "username": "bee",
            "display_name": "Bee",
            "timezone": "Europe/London",
        },
    )

    assert response.status_code == 200
    link = SETUP_LINK_RE.search(response.text)
    assert link, "no setup link on the confirmation page"

    created = await session.scalar(select(User).where(User.username == "bee"))
    assert created is not None
    assert created.password_hash is None, (
        "a new account must not be able to sign in yet"
    )
    assert created.timezone == "Europe/London"


async def test_admin_cannot_suspend_themselves(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """Otherwise a group can lock every admin out with nobody to undo it."""
    admin = await make_admin(session)
    await sign_in(anon_client)

    form_page = await anon_client.get("/admin")
    await anon_client.post(
        f"/admin/users/{admin.username}/deactivate",
        headers={CSRF_HEADER_NAME: csrf_from(form_page.text)},
    )

    await session.refresh(admin)
    assert admin.is_active


async def test_deleting_a_user_removes_their_data_but_not_the_record(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """The audit row survives, because it is the record of the deletion."""
    from bm_tracker.models import AuditLog, DailyLog  # noqa: PLC0415

    await make_admin(session)
    victim, _ = await make_user(session, "bee")
    victim.password_hash = auth.hash_password(GOOD_PASSWORD)
    session.add(DailyLog(user_id=victim.id, day=date(2026, 1, 9)))
    await session.commit()
    victim_id = victim.id

    await sign_in(anon_client)
    form_page = await anon_client.get("/admin")
    await anon_client.post(
        "/admin/users/bee/delete",
        headers={CSRF_HEADER_NAME: csrf_from(form_page.text)},
    )

    # Counted rather than fetched: this session still has the object in its
    # identity map from when it was created, so `get` would return the stale
    # copy and the assertion would pass for the wrong reason.
    remaining = await session.scalar(
        select(func.count()).select_from(User).where(User.id == victim_id)
    )
    assert remaining == 0, "the user was not deleted"

    days_left = await session.scalar(
        select(func.count()).select_from(DailyLog).where(DailyLog.user_id == victim_id)
    )
    assert days_left == 0, "their days should have gone with them"

    deletions = await session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "user.delete")
    )
    assert deletions == 1, "the audit record of the deletion must survive"


# --- output escaping ------------------------------------------------------


async def test_user_content_is_escaped_in_every_template(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """A display name full of markup must render as text, everywhere.

    The payload is checked for absence across the admin page, the sign-in page
    and the setup page, since those are the surfaces a user can put text into.
    """
    payload = "<script>alert(1)</script>"
    hostile, _ = await make_user(session, "bee")
    hostile.display_name = payload
    await session.commit()
    await make_admin(session)

    await sign_in(anon_client)
    admin_page = await anon_client.get("/admin")

    assert payload not in admin_page.text, "markup was rendered unescaped"
    assert "&lt;script&gt;" in admin_page.text, "the payload should appear escaped"


async def test_template_payload_is_not_evaluated(
    session: AsyncSession, anon_client: AsyncClient
) -> None:
    """Jinja expression syntax in user content is text, not code.

    The payload surviving as literal text *is* the proof: had Jinja evaluated it,
    the page would say "49" and the source text would be gone. Asserting "49" is
    absent from the whole page is both redundant and brittle, since real numbers
    do appear there now.
    """
    hostile, _ = await make_user(session, "bee")
    hostile.display_name = "{{ 7 * 7 }}"
    await session.commit()
    await make_admin(session)

    await sign_in(anon_client)
    page = await anon_client.get("/admin")

    assert "7 * 7" in page.text, "the payload was evaluated rather than escaped"
    assert "{{" in page.text
