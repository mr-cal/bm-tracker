"""Admin routes: creating, suspending and removing accounts."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select

from bm_tracker.dependencies import AdminUser, DbSession, csrf_token, verify_csrf
from bm_tracker.models import (
    AchievementUnlock,
    BmEntry,
    CelebrationSeen,
    DailyLog,
    Invite,
    User,
    UserFact,
)
from bm_tracker.services import audit_service, auth_service, invite_service
from bm_tracker.timezones import DEFAULT_TIMEZONE

router = APIRouter(prefix="/admin", tags=["admin"])


def _templates(request: Request) -> Jinja2Templates:
    """Return the app's template environment.

    Args:
        request: The incoming request.

    Returns:
        The configured `Jinja2Templates`.

    """
    templates: Jinja2Templates = request.app.state.templates
    return templates


async def _find_user(session: DbSession, username: str) -> User | None:
    """Return a user by username, or `None`.

    Args:
        session: The database session.
        username: The slug to look up.

    Returns:
        The `User`, if one matches.

    """
    return await session.scalar(
        select(User).where(User.username == username.strip().lower())
    )


async def _admin_page(
    request: Request,
    session: DbSession,
    admin: User,
    *,
    created: dict[str, object] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render the admin page with its supporting rows.

    Args:
        request: The incoming request.
        session: The database session.
        admin: The signed-in administrator.
        created: Details of a just-created account, if any.
        error: An error message, if any.
        status_code: The response status.

    Returns:
        The rendered page.

    """
    users = list((await session.scalars(select(User).order_by(User.username))).all())

    live_counts = dict.fromkeys(
        (await session.scalars(select(Invite.user_id).distinct())).all(), 0
    )
    for invite in (
        await session.scalars(select(Invite).where(Invite.used_at.is_(None)))
    ).all():
        live_counts[invite.user_id] = live_counts.get(invite.user_id, 0) + 1

    return _templates(request).TemplateResponse(
        request,
        "admin/index.html",
        {
            "default_timezone": DEFAULT_TIMEZONE,
            "users": users,
            "live_invite_counts": live_counts,
            "admin": admin,
            "created": created,
            "error": error,
            "csrf_token": csrf_token(request),
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse, response_model=None)
@router.get("/", response_class=HTMLResponse, response_model=None)
async def admin_index(
    request: Request, session: DbSession, admin: AdminUser
) -> HTMLResponse:
    """List every account, with its live invite status."""
    return await _admin_page(request, session, admin)


@router.post("/users", response_class=HTMLResponse, response_model=None)
async def create_user(
    request: Request,
    session: DbSession,
    admin: AdminUser,
) -> HTMLResponse:
    """Create an account and show its one-time setup link exactly once."""
    form = await request.form()
    verify_csrf(
        request,
        request.headers.get("X-CSRF-Token") or str(form.get("csrf_token", "")),
    )

    username = str(form.get("username", "")).strip().lower()
    display_name = str(form.get("display_name", "")).strip()
    timezone_name = str(form.get("timezone", "")).strip() or DEFAULT_TIMEZONE
    make_admin = form.get("is_admin") == "on"

    if not username:
        return await _admin_page(
            request, session, admin, error="A username is required.", status_code=400
        )

    try:
        user = await auth_service.create_user(
            session,
            username,
            display_name,
            is_admin=make_admin,
            timezone_name=timezone_name,
        )
        await session.flush()
        invite, raw_token = await invite_service.issue(session, user)
        await audit_service.record(
            session,
            action="user.create",
            user_id=admin.id,
            entity_type="user",
            entity_id=str(user.id),
            detail={"username": user.username},
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        return await _admin_page(
            request, session, admin, error=str(exc), status_code=400
        )

    return await _admin_page(
        request,
        session,
        admin,
        created={
            "username": user.username,
            "display_name": user.display_name,
            "setup_path": f"/setup/{raw_token}",
            "hours_valid": round(
                (invite.expires_at - invite.created_at).total_seconds() / 3600
            ),
        },
    )


@router.post("/users/{username}/deactivate")
async def deactivate(
    request: Request,
    username: str,
    session: DbSession,
    admin: AdminUser,
) -> RedirectResponse:
    """Suspend an account and kill its live sessions.

    An admin cannot suspend themselves: that is how a group accidentally locks
    everybody out of administration with nobody left to undo it.
    """
    verify_csrf(request, request.headers.get("X-CSRF-Token"))
    user = await _find_user(session, username)
    if user is not None and user.id != admin.id:
        user.is_active = False
        auth_service.invalidate_sessions(user)
        await audit_service.record(
            session,
            action="user.deactivate",
            user_id=admin.id,
            entity_type="user",
            entity_id=str(user.id),
            detail={"username": user.username},
        )
        await session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{username}/activate")
async def reactivate(
    request: Request,
    username: str,
    session: DbSession,
    admin: AdminUser,
) -> RedirectResponse:
    """Restore a suspended account."""
    verify_csrf(request, request.headers.get("X-CSRF-Token"))
    user = await _find_user(session, username)
    if user is not None:
        user.is_active = True
        await audit_service.record(
            session,
            action="user.activate",
            user_id=admin.id,
            entity_type="user",
            entity_id=str(user.id),
            detail={"username": user.username},
        )
        await session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{username}/reissue")
async def reissue(
    request: Request,
    username: str,
    session: DbSession,
    admin: AdminUser,
) -> RedirectResponse:
    """Issue a fresh setup link for an account that has not redeemed one."""
    verify_csrf(request, request.headers.get("X-CSRF-Token"))
    user = await _find_user(session, username)
    if user is not None:
        await invite_service.issue(session, user)
        await audit_service.record(
            session,
            action="user.reissue_invite",
            user_id=admin.id,
            entity_type="user",
            entity_id=str(user.id),
            detail={"username": user.username},
        )
        await session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{username}/admin")
async def toggle_admin(
    request: Request,
    username: str,
    session: DbSession,
    admin: AdminUser,
) -> RedirectResponse:
    """Grant or revoke admin rights.

    Demotion bumps the session version too: an admin who loses the role must
    stop being one on their next request, not in thirty days.
    """
    verify_csrf(request, request.headers.get("X-CSRF-Token"))
    user = await _find_user(session, username)
    if user is not None and user.id != admin.id:
        user.is_admin = not user.is_admin
        auth_service.invalidate_sessions(user)
        await audit_service.record(
            session,
            action="user.set_admin",
            user_id=admin.id,
            entity_type="user",
            entity_id=str(user.id),
            detail={"username": user.username, "status": str(user.is_admin)},
        )
        await session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{username}/delete")
async def delete_user(
    request: Request,
    username: str,
    session: DbSession,
    admin: AdminUser,
) -> RedirectResponse:
    """Remove an account and everything it owns. Irreversible.

    There is no self-service deletion: the app is invite-only for a handful of
    people, and everybody can see everybody's data, so removal is an admin
    decision rather than a personal one. The audit row is written first and
    carries no foreign key, so the record that this happened survives the
    deletion.
    """
    verify_csrf(request, request.headers.get("X-CSRF-Token"))
    user = await _find_user(session, username)
    if user is None or user.id == admin.id:
        return RedirectResponse("/admin", status_code=303)

    # An explicit count rather than len(user.daily_logs): a lazy relationship
    # load in an async route needs an await, and counting in SQL avoids
    # loading a user's whole history to produce a number for the audit row.
    day_count = int(
        await session.scalar(
            select(func.count())
            .select_from(DailyLog)
            .where(DailyLog.user_id == user.id)
        )
        or 0
    )
    await audit_service.record(
        session,
        action="user.delete",
        user_id=admin.id,
        entity_type="user",
        entity_id=str(user.id),
        detail={"username": user.username, "row_count": day_count},
    )
    await session.delete(user)
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post(
    "/users/{username}/reset", response_class=HTMLResponse, response_model=None
)
async def reset_user(
    request: Request,
    username: str,
    session: DbSession,
    admin: AdminUser,
) -> RedirectResponse:
    """Wipe everything a person has done, and leave them able to log in.

    Not deletion — the account, its password, its name, its timezone, its theme
    and whether it is an administrator all survive. What goes is the year of
    logging: entries, days, notes, streak records, unlocked achievements, which
    celebration lines they have seen, their derived facts and any outstanding
    setup link. The result is an account that has logged in and done nothing.

    The audit log is deliberately *not* cleared. It is the record that this
    happened and who did it, and a reset that erased its own evidence would be
    the one operation nobody could investigate afterwards.

    The session version is bumped, so a browser holding an old cookie is signed
    out rather than showing a stale page next to an empty dashboard.

    Irreversible for the logging history. The form asks for the username to be
    typed back, because this is the one button on the page that cannot be undone
    by clicking it again.
    """
    verify_csrf(request, request.headers.get("X-CSRF-Token"))
    user = await _find_user(session, username)
    if user is None:
        return RedirectResponse("/admin", status_code=303)

    form = await request.form()
    if str(form.get("confirm", "")).strip() != user.username:
        return RedirectResponse("/admin", status_code=303)

    # Entries are the exception: they belong to a person through their day, not
    # through a user_id of their own, so they are reached by a join. Everything
    # else is keyed straight off the user.
    rows = int(
        await session.scalar(
            select(func.count())
            .select_from(BmEntry)
            .join(DailyLog, DailyLog.id == BmEntry.daily_log_id)
            .where(DailyLog.user_id == user.id)
        )
        or 0
    )
    await session.execute(
        delete(BmEntry).where(
            BmEntry.daily_log_id.in_(
                select(DailyLog.id).where(DailyLog.user_id == user.id)
            )
        )
    )
    for model in (DailyLog, AchievementUnlock, CelebrationSeen, UserFact, Invite):
        rows += int(
            await session.scalar(
                select(func.count()).select_from(model).where(model.user_id == user.id)
            )
            or 0
        )
        await session.execute(delete(model).where(model.user_id == user.id))

    user.session_version += 1
    await audit_service.record(
        session,
        action="user.reset",
        user_id=admin.id,
        entity_type="user",
        entity_id=str(user.id),
        detail={"username": user.username, "rows_removed": rows},
    )
    await session.commit()
    return RedirectResponse("/admin", status_code=303)
