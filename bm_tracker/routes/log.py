"""Routes for logging a day.

Two distinct actions share one page, because they are two distinct outcomes
rather than one form with a checkbox: logging a bowel movement, and recording
that there wasn't one. The second is not an error state — it is the thing a
large share of days actually are.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from bm_tracker import bristol, celebrate, forms, strain
from bm_tracker.achievements import engine as achievements
from bm_tracker.dependencies import (
    CSRF_HEADER_NAME,
    AuthenticatedUser,
    DbSession,
    csrf_token,
    verify_csrf,
)
from bm_tracker.models import BmEntry, DailyLog, User
from bm_tracker.services import audit_service, bm_service
from bm_tracker.timezones import now_in, parse_date

#: Matches the configured default; the app setting is applied where scoring runs.
QUICK_WINDOW_MINUTES = 10

#: Where a post-log celebration waits between the redirect and the render.
FLASH_KEY = "celebration"


@dataclass(frozen=True, slots=True)
class Celebration:
    """What to say after a write, and what it earned.

    A dataclass rather than a dict, so the flash payload is checked by `ty`
    instead of being `object` at every use.
    """

    said: str | None = None
    unlocked: tuple[str, ...] = ()


router = APIRouter(tags=["log"])


def _templates(request: Request) -> Jinja2Templates:
    """Return the app's template environment.

    Args:
        request: The incoming request.

    Returns:
        The configured `Jinja2Templates`.

    """
    templates: Jinja2Templates = request.app.state.templates
    return templates


async def _render_log(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
    day: date,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render the log page for a day.

    Args:
        request: The incoming request.
        session: The database session.
        user: The signed-in user.
        day: The occurrence date being viewed.
        error: An error message, if any.
        status_code: The status to return, so a rejected submission is a 400
            rather than a 200 that looks like it worked.

    Returns:
        The rendered page.

    """
    row = await bm_service.get_day(session, user, day)
    entries: list[BmEntry] = []
    if row is not None:
        entries = list(
            (
                await session.scalars(
                    select(BmEntry)
                    .where(BmEntry.daily_log_id == row.id)
                    .order_by(BmEntry.occurred_local)
                )
            ).all()
        )

    local_today, now = now_in(user.timezone)
    # Popped, not read: a refresh after logging must not replay the
    # celebration or the unlock, only the log.
    flash = request.session.pop(FLASH_KEY, None)
    return _templates(request).TemplateResponse(
        request,
        "log/index.html",
        {
            "user": user,
            "flash": flash,
            "day": day,
            "day_of_week": day.strftime("%A"),
            "today": local_today,
            "now": now,
            "is_today": day == local_today,
            "is_future": day > local_today,
            "log": row,
            "entries": [bm_service.entry_payload(entry) for entry in entries],
            "bristol_scale": bristol.BRISTOL_SCALE,
            "strain_scale": strain.STRAIN_SCALE,
            "strain_by_value": {s.value: s for s in strain.STRAIN_SCALE},
            "csrf_token": csrf_token(request),
            "nav": "log",
            "error": error,
        },
        status_code=status_code,
    )


async def _reload(session: DbSession, user_id: int) -> User:
    """Return a user freshly attached, for use after a rollback.

    A rollback expires every object the session was holding, so re-rendering
    after a failed write would trigger a lazy refresh mid-request, which an
    async engine cannot do. The id is passed in rather than read off the
    expired instance for the same reason: reading it is itself a refresh.

    Args:
        session: The session to re-read through.
        user_id: The user's id, captured before the rollback.

    Returns:
        The reloaded `User`, or a bare one if the row has gone.

    """
    fresh = await session.get(User, user_id)
    return (
        fresh if fresh is not None else User(id=user_id, username="", display_name="")
    )


def _back_to_log(
    request: Request, day: date, celebration: Celebration
) -> RedirectResponse:
    """Redirect back to the day, carrying any celebration in the session.

    A session flash rather than query parameters: the message is not something to
    bookmark, share, or refresh into a duplicate, and the URL stays the plain
    address of the day.

    Args:
        request: The incoming request.
        day: The day being viewed afterwards.
        celebration: What to say, and what was unlocked.

    Returns:
        The redirect.

    """
    if celebration.said or celebration.unlocked:
        request.session[FLASH_KEY] = {
            "said": celebration.said,
            "unlocked": list(celebration.unlocked),
        }
    return RedirectResponse(f"/log?date={day.isoformat()}", status_code=303)


def _event_flags(entry: BmEntry, day: DailyLog) -> dict[str, bool]:
    """Return which celebration events this entry triggers.

    The rarer event wins, so an entry recorded within ten minutes *and* carrying
    a note gets the quick-entry line rather than a generic one.

    Args:
        entry: The entry just written.
        day: The day it belongs to.

    Returns:
        A mapping of event name to whether it applies.

    """
    from bm_tracker import scoring  # noqa: PLC0415

    return {
        "quick_entry": scoring.is_quick(
            entry.created_at, entry.occurred_local, QUICK_WINDOW_MINUTES
        ),
        "note_added": entry.has_note or (day.notes is not None and day.n_bms == 0),
        "streak": entry.daily_log_id is not None and day.n_bms == 1,
    }


async def _celebrate_after(
    session: DbSession,
    user: AuthenticatedUser,
    event: str,
    *,
    extra: dict[str, bool] | None = None,
) -> Celebration:
    """Evaluate achievements, record new unlocks, and choose a line to say.

    Runs on every write, and is idempotent: an achievement already earned this
    year is never recorded twice.

    Args:
        session: The session to write through.
        user: The user who just logged something.
        event: The event that just happened.
        extra: Other events this action triggered, used to pick the rarest line.

    Returns:
        The chosen line and any newly earned achievement keys.

    """
    local_today, _ = now_in(user.timezone)
    unlocks = await achievements.evaluate(session, user, local_today.year)
    await achievements.record(session, unlocks, user.id, local_today.year)

    candidates = [event, *(name for name, on in (extra or {}).items() if on)]
    said = None
    for name in candidates:
        said = await celebrate.pick(session, user.id, name)
        if said is not None:
            break

    return Celebration(said=said, unlocked=tuple(u.achievement.name for u in unlocks))


@router.get("/log", response_class=HTMLResponse, response_model=None)
async def log_page(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> HTMLResponse:
    """Show the log form for a day, defaulting to today.

    Args:
        request: The incoming request.
        session: The database session.
        user: The authenticated user.

    Returns:
        The rendered page.

    """
    return await _render_log(request, session, user, _requested_day(request, user))


def _requested_day(request: Request, user: AuthenticatedUser) -> date:
    """Return the day the request is asking about.

    Args:
        request: The incoming request.
        user: The authenticated user, for the default.

    Returns:
        The requested day, or today.

    """
    requested = parse_date(request.query_params.get("date", ""))
    local_today, _ = now_in(user.timezone)
    return requested if requested is not None else local_today


@router.post("/log/bm", response_class=HTMLResponse, response_model=None)
async def submit_bm(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> HTMLResponse | RedirectResponse:
    """Record one bowel movement."""
    form = await request.form()
    forms.guard_csrf(request, form)
    day = parse_date(forms.guard_field(form, "day"))
    if day is None:
        return RedirectResponse("/log", status_code=303)
    user_id = user.id  # captured before a rollback can expire the instance

    try:
        entry = await bm_service.log_bm(
            session,
            user,
            day,
            occurred_local=bm_service.form_datetime(
                day, forms.guard_field(form, "time")
            ),
            bristol_type=bristol.parse_type(forms.guard_field(form, "bristol_type")),
            spicy=forms.form_flag(form, "spicy"),
            urgent=forms.form_flag(form, "urgent"),
            strain=strain.parse_strain(forms.form_text(form, "strain")),
            notes=forms.form_text(form, "notes"),
        )
        # `log_bm` has just created the day, so this read always succeeds; it
        # is here for the note state the celebration needs.
        row = await bm_service.get_day(session, user, day)
        assert row is not None  # noqa: S101 - guaranteed by the call above
        await audit_service.record(
            session,
            action="entry.create",
            user_id=user.id,
            entity_type="bm_entry",
            entity_id=str(entry.id),
            detail={"day": day.isoformat(), "bristol_type": entry.bristol_type},
        )
        celebration = await _celebrate_after(
            session, user, "log_any", extra=_event_flags(entry, row)
        )
        await session.commit()
    except (ValueError, bm_service.DayInFutureError) as exc:
        await session.rollback()
        return await _render_log(
            request,
            session,
            await _reload(session, user_id),
            day,
            error=str(exc),
            status_code=400,
        )

    return _back_to_log(request, day, celebration)


@router.post("/log/nothing", response_class=HTMLResponse, response_model=None)
async def submit_nothing(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> HTMLResponse | RedirectResponse:
    """Record a day on which there was nothing to report.

    This is a scored, streak-extending outcome, not an empty state.
    """
    form = await request.form()
    forms.guard_csrf(request, form)
    day = parse_date(forms.guard_field(form, "day"))
    if day is None:
        return RedirectResponse("/log", status_code=303)
    user_id = user.id

    try:
        await bm_service.log_nothing_today(
            session, user, day, notes=forms.form_text(form, "notes")
        )
        await audit_service.record(
            session,
            action="day.log",
            user_id=user.id,
            entity_type="daily_log",
            entity_id=day.isoformat(),
            detail={"day": day.isoformat(), "n_bms": 0},
        )
        row = await bm_service.get_day(session, user, day)
        celebration = await _celebrate_after(
            session,
            user,
            "log_none",
            extra={"note_added": bool(row and row.is_note_live)},
        )
        await session.commit()
    except bm_service.DayInFutureError as exc:
        await session.rollback()
        return await _render_log(
            request,
            session,
            await _reload(session, user_id),
            day,
            error=str(exc),
            status_code=400,
        )

    return _back_to_log(request, day, celebration)


@router.post("/log/note", response_class=HTMLResponse, response_model=None)
async def submit_note(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> HTMLResponse | RedirectResponse:
    """Create or replace the note written against a day."""
    form = await request.form()
    forms.guard_csrf(request, form)
    day = parse_date(forms.guard_field(form, "day"))
    if day is None:
        return RedirectResponse("/log", status_code=303)
    user_id = user.id

    try:
        row = await bm_service.set_day_note(
            session, user, day, forms.form_text(form, "notes")
        )
        await audit_service.record(
            session,
            action="day.update",
            user_id=user.id,
            entity_type="daily_log",
            entity_id=str(row.id),
            detail={"day": day.isoformat(), "n_bms": row.n_bms},
        )
        # No message: editing a note is not a log. The engine still runs, since
        # a note can be what unlocks something.
        celebration = await _celebrate_after(session, user, "note_added", extra={})
        await session.commit()
    except bm_service.DayInFutureError as exc:
        await session.rollback()
        return await _render_log(
            request,
            session,
            await _reload(session, user_id),
            day,
            error=str(exc),
            status_code=400,
        )

    return _back_to_log(request, day, celebration)


@router.post("/log/entry/{entry_id}/delete")
async def delete_entry(
    entry_id: int,
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> RedirectResponse:
    """Delete one bowel movement."""
    verify_csrf(request, request.headers.get(CSRF_HEADER_NAME))
    entry = await session.get(BmEntry, entry_id)
    day = None
    if entry is not None:
        day = await session.get(DailyLog, entry.daily_log_id)
        await bm_service.delete_entry(session, entry, acting_user=user)
        await audit_service.record(
            session,
            action="entry.delete",
            user_id=user.id,
            entity_type="bm_entry",
            entity_id=str(entry_id),
        )
        await session.commit()
    if day is not None:
        return RedirectResponse(f"/log?date={day.day.isoformat()}", status_code=303)
    return RedirectResponse("/log", status_code=303)


@router.post("/log/day/{day_id}/delete")
async def delete_day(
    day_id: int,
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> RedirectResponse:
    """Delete a whole day and everything on it."""
    verify_csrf(request, request.headers.get(CSRF_HEADER_NAME))
    row = await session.get(DailyLog, day_id)
    if row is not None:
        target = row.day
        await bm_service.delete_day(session, row, acting_user=user)
        await audit_service.record(
            session,
            action="day.delete",
            user_id=user.id,
            entity_type="daily_log",
            entity_id=str(day_id),
        )
        await session.commit()
        return RedirectResponse(f"/log?date={target.isoformat()}", status_code=303)
    return RedirectResponse("/log", status_code=303)
