"""Routes for logging a day.

Two distinct actions share one page, because they are two distinct outcomes
rather than one form with a checkbox: logging a bowel movement, and recording
that there wasn't one. The second is not an error state — it is the thing a
large share of days actually are.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData

from bm_tracker import bristol, celebrate, forms, strain
from bm_tracker.achievements import engine as achievements
from bm_tracker.dependencies import (
    AuthenticatedUser,
    DbSession,
    csrf_token,
)
from bm_tracker.models import BmEntry, DailyLog, User
from bm_tracker.services import audit_service, bm_service, rewards
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
    # Mappings rather than names: the reward screen has to say what you *did* to
    # earn something, and "The Marathon" on its own does not say five in a day.
    unlocked: list[dict[str, object]] = field(default_factory=list)
    # The itemised breakdown of what the last write earned, so the reward
    # screen can show the rules one at a time rather than a single number.
    reward: list[dict[str, object]] = field(default_factory=list)
    reward_total: int = 0


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
    user: User,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render the logging form, pre-filled with now.

    There is no day in the URL and nothing on the page describes a day. The
    form is a statement about a moment, not a view of a day, so it does not
    load the day's rows to show alongside it: that is what `/dashboard` and
    `/dashboard/entries` are for, and duplicating them here meant the logging
    form was carrying a query it did not need.

    Args:
        request: The incoming request.
        user: The signed-in user.
        error: An error message, if any.
        status_code: The status to return, so a rejected submission is a 400
            rather than a 200 that looks like it worked.

    Returns:
        The rendered page.

    """
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
            "today": local_today,
            "now": now,
            "bristol_scale": bristol.BRISTOL_SCALE,
            "strain_scale": strain.STRAIN_SCALE,
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


def _reward_row(line: rewards.RewardLine) -> dict[str, object]:
    """Return a reward line as something the session can hold.

    The session is JSON, so a dataclass cannot go in it as one.

    Args:
        line: The line to record.

    Returns:
        A mapping of label, points and detail.

    """
    return {"label": line.label, "points": line.points, "detail": line.detail}


def _back_to_log(request: Request, celebration: Celebration) -> RedirectResponse:
    """Redirect back to the form, carrying any celebration in the session.

    A session flash rather than query parameters: the message is not something to
    bookmark, share, or refresh into a duplicate, and the URL stays the plain
    address of the form, which takes no arguments.

    Args:
        request: The incoming request.
        celebration: What to say, and what was unlocked.

    Returns:
        The redirect.

    """
    if celebration.said or celebration.unlocked or celebration.reward:
        request.session[FLASH_KEY] = {
            "said": celebration.said,
            "unlocked": list(celebration.unlocked),
            "reward": list(celebration.reward),
            "reward_total": celebration.reward_total,
        }
    return RedirectResponse("/log", status_code=303)


def _return_to(form: FormData) -> str:
    """Return where a delete should send the user afterwards.

    Only a path on this site is honoured. A redirect target from a form is
    attacker-controlled, and an open redirect off a page that just deleted
    something is a good way to lose the last of somebody's trust.

    Args:
        form: The submitted form.

    Returns:
        The path to redirect to, or the entries list.

    """
    raw = form.get("return_to")
    if not isinstance(raw, str) or not raw.startswith("/") or raw.startswith("//"):
        return "/dashboard/entries"
    return raw


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


def _bristol_from(choice: str) -> str:
    """Return the Bristol type encoded in a `bm:<type>` choice.

    Args:
        choice: The submitted choice, "nothing" or "bm:<type>".

    Returns:
        The raw type as it appears in the form value.

    Raises:
        ValueError: If the choice is not a BM, so `parse_type` can report it.

    """
    if not choice.startswith(CHOICE_BM_PREFIX):
        msg = "Pick a Bristol type, or choose Nothing today."
        raise ValueError(msg)
    return choice[len(CHOICE_BM_PREFIX) :]


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

    return Celebration(
        said=said,
        unlocked=[
            {
                "key": u.achievement.key,
                "name": u.achievement.name,
                "description": u.achievement.description,
                "icon": u.achievement.icon,
                "points": u.achievement.points,
            }
            for u in unlocks
        ],
    )


@router.get("/log", response_class=HTMLResponse, response_model=None)
async def log_page(
    request: Request,
    user: AuthenticatedUser,
) -> HTMLResponse:
    """Show the logging form, pre-filled with the current date and time.

    Args:
        request: The incoming request.
        user: The authenticated user.

    Returns:
        The rendered page.

    """
    return await _render_log(request, user)


CHOICE_NOTHING = "nothing"
CHOICE_BM_PREFIX = "bm:"


@router.post("/log", response_class=HTMLResponse, response_model=None)
async def submit_log(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> HTMLResponse | RedirectResponse:
    """Record what happened on a day: a BM, or nothing at all.

    One endpoint for both, because the form offers both as cards in the same
    grid and a form that posts somewhere different depending on which card you
    tapped needs JavaScript to get right. Here the server decides, and the
    decision is one comparison.

    The per-BM fields are ignored outright when the day is logged as empty. The
    interface greys them out, but that is a convenience: a request that carries
    `spicy=on` alongside `choice=nothing` is not going to be allowed to record a
    spicy bowel movement on a day with no bowel movements in it.
    """
    form = await request.form()
    forms.guard_csrf(request, form)
    day = parse_date(forms.guard_field(form, "date"))
    if day is None:
        return RedirectResponse("/log", status_code=303)
    user_id = user.id  # captured before a rollback can expire the instance
    notes = forms.form_text(form, "notes")
    window = request.app.state.settings.quick_entry_window_minutes
    lines: list[rewards.RewardLine] = []

    # `choice` is the single source of truth for what happened: either "nothing"
    # or "bm:<type>". A separate `bristol_type` field would be a second thing to
    # disagree with it.
    choice = forms.guard_field(form, "choice")
    try:
        if choice == CHOICE_NOTHING:
            await bm_service.log_nothing_today(session, user, day, notes=notes)
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
        else:
            entry = await bm_service.log_bm(
                session,
                user,
                day,
                occurred_local=bm_service.form_datetime(
                    day, forms.guard_field(form, "time")
                ),
                bristol_type=bristol.parse_type(_bristol_from(choice)),
                spicy=forms.form_flag(form, "spicy"),
                urgent=forms.form_flag(form, "urgent"),
                strain=strain.parse_strain(forms.form_text(form, "strain")),
                notes=notes,
            )
            # `log_bm` has just created the day, so this read always succeeds;
            # it is here for the note state the celebration needs.
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
            lines = await rewards.for_entry(
                session, entry, row, user, window_minutes=window
            )
        await session.commit()
        if lines:
            celebration = replace(
                celebration,
                reward=[_reward_row(line) for line in lines],
                reward_total=rewards.total_of(lines),
            )
    except (ValueError, bm_service.DayInFutureError) as exc:
        await session.rollback()
        return await _render_log(
            request,
            await _reload(session, user_id),
            error=str(exc),
            status_code=400,
        )

    return _back_to_log(request, celebration)


@router.post("/log/entry/{entry_id}/delete")
async def delete_entry(
    entry_id: int,
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> RedirectResponse:
    """Delete one bowel movement.

    The token is read from the form field rather than a header: this is posted
    by an ordinary button on a page, and reading only the header meant the
    button rejected its own submission with a 403.
    """
    form = await request.form()
    forms.guard_csrf(request, form)
    entry = await session.get(BmEntry, entry_id)
    if entry is not None:
        await bm_service.delete_entry(session, entry, acting_user=user)
        await audit_service.record(
            session,
            action="entry.delete",
            user_id=user.id,
            entity_type="bm_entry",
            entity_id=str(entry_id),
        )
        await session.commit()
    return RedirectResponse(_return_to(form), status_code=303)
