"""The group feed, the people index, and a single participant.

Everything here goes through `services/visibility.py`. A route that decided what
a viewer may see for itself would be a leak waiting to happen, so none of them
does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from bm_tracker import bristol, scoring, strain
from bm_tracker.achievements.engine import REGISTRY
from bm_tracker.achievements.registry import RegistryError
from bm_tracker.dependencies import AuthenticatedUser, DbSession, csrf_token
from bm_tracker.forms import int_arg
from bm_tracker.models import AchievementUnlock, BmEntry, DailyLog, User
from bm_tracker.services import feed_service, visibility
from bm_tracker.timezones import now_in

router = APIRouter(tags=["people"])


@dataclass(frozen=True, slots=True)
class PublishedNote:
    """A note a person has made public, attributed to its day."""

    day: date
    text: str


@dataclass(frozen=True, slots=True)
class Badge:
    """One earned badge, with the registry's own wording.

    The name and description come from the registry rather than being derived
    from the key, so an icon's tooltip can never say something different from
    what the achievement actually is.
    """

    key: str
    name: str
    description: str
    icon: str
    tier: str
    points: int


@dataclass(frozen=True, slots=True)
class PersonRow:
    """One line of the people roster."""

    user: User
    score: scoring.UserScore
    badges: tuple[Badge, ...]
    is_you: bool


def _templates(request: Request) -> Jinja2Templates:
    """Return the app's template environment.

    Args:
        request: The incoming request.

    Returns:
        The configured `Jinja2Templates`.

    """
    templates: Jinja2Templates = request.app.state.templates
    return templates


def _window(request: Request) -> int:
    """Return the configured ten-minute bonus window.

    Args:
        request: The incoming request.

    Returns:
        The window in minutes.

    """
    return int(request.app.state.settings.quick_entry_window_minutes)


@router.get("/", response_class=HTMLResponse, response_model=None)
async def feed(
    request: Request, session: DbSession, user: AuthenticatedUser
) -> HTMLResponse:
    """Render a page of the feed, one continuous timeline.

    No year selector and no year argument: paging back far enough crosses
    1 January without a seam. A year boundary in a scroll of history is a thing
    the reader has to notice and do something about, and the whole reason to
    look at your own year is to see how it runs.
    """
    page = int_arg(request.query_params.get("page"), 1)
    per_page = feed_service.PAGE_SIZE
    items = await feed_service.feed_items(
        session,
        viewer=user,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    # Asking for one item past this page is how we know whether to offer a
    # "newer" link, without a second count query that could disagree with the
    # page it is counting.
    lookahead = await feed_service.feed_items(
        session, viewer=user, limit=1, offset=page * per_page
    )
    return _templates(request).TemplateResponse(
        request,
        "feed/index.html",
        {
            "user": user,
            "today": now_in(user.timezone)[0],
            "items": items,
            "page": page,
            "has_next": bool(lookahead),
            "per_page": per_page,
            "nav": "feed",
            "kinds": feed_service.KINDS,
            "bristol_by_value": {t.value: t for t in bristol.BRISTOL_SCALE},
            "strain_by_value": {s.value: s for s in strain.STRAIN_SCALE},
            "csrf_token": csrf_token(request),
        },
    )


def _year(request: Request, user: AuthenticatedUser) -> int:
    """Return the year being viewed, defaulting to the user's current year.

    Args:
        request: The incoming request.
        user: The authenticated user, for the default.

    Returns:
        The calendar year.

    """
    raw = request.query_params.get("year", "")
    current, _ = now_in(user.timezone)
    return int(raw) if raw.isdigit() else current.year


@router.get("/people", response_class=HTMLResponse, response_model=None)
async def people(
    request: Request, session: DbSession, user: AuthenticatedUser
) -> HTMLResponse:
    """Everyone, as a roster of streaks, points and badges."""
    year = _year(request, user)
    users = list(
        (
            await session.scalars(
                select(User).where(User.is_active.is_(True)).order_by(User.username)
            )
        ).all()
    )
    rows = sorted(
        [
            PersonRow(
                user=person,
                score=await scoring.score_year(
                    session, person, year, window_minutes=_window(request)
                ),
                badges=await _badges(session, person.id, year),
                is_you=person.id == user.id,
            )
            for person in users
        ],
        key=lambda row: row.score.logging_points,
        reverse=True,
    )

    return _templates(request).TemplateResponse(
        request,
        "people/index.html",
        {
            "user": user,
            "year": year,
            "rows": rows,
            "nav": "people",
            "csrf_token": csrf_token(request),
        },
    )


async def published_notes(session: DbSession, user_id: int) -> list[PublishedNote]:
    """Return every note a person has published, newest day first.

    Both kinds, because notes are exactly what other users are allowed to see: a
    note on a specific BM and a note on an empty day are equally part of the
    published record, and showing one without the other would be arbitrary.
    Superseded day-notes are excluded — they have been overtaken by a BM.

    Args:
        session: The session to read through.
        user_id: Whose notes to return.

    Returns:
        The published notes, newest first.

    """
    notes: list[PublishedNote] = []

    day_notes = (
        await session.scalars(
            select(DailyLog)
            .where(
                DailyLog.user_id == user_id,
                DailyLog.n_bms == 0,
                DailyLog.notes.is_not(None),
            )
            .order_by(DailyLog.day.desc())
        )
    ).all()
    notes += [
        PublishedNote(day=row.day, text=row.notes or "")
        for row in day_notes
        if row.is_note_live
    ]

    entry_notes = (
        await session.execute(
            select(BmEntry.notes, DailyLog.day)
            .join(DailyLog, DailyLog.id == BmEntry.daily_log_id)
            .where(DailyLog.user_id == user_id, BmEntry.notes.is_not(None))
            .order_by(DailyLog.day.desc(), BmEntry.occurred_local.desc())
        )
    ).all()
    notes += [
        PublishedNote(day=day, text=text.strip())
        for text, day in entry_notes
        if text and text.strip()
    ]

    notes.sort(key=lambda note: note.day, reverse=True)
    return notes


async def _badges(session: DbSession, user_id: int, year: int) -> tuple[Badge, ...]:
    """Return a person's earned badges for the year, ready to render.

    Each carries the registry's own name and description rather than the bare
    key, so an icon's tooltip cannot drift from what the achievement is.

    Args:
        session: The session to read through.
        user_id: Whose badges.
        year: The calendar year.

    Returns:
        The badges, most recent first.

    """
    rows = (
        await session.scalars(
            select(AchievementUnlock)
            .where(AchievementUnlock.user_id == user_id, AchievementUnlock.year == year)
            .order_by(AchievementUnlock.unlocked_at.desc())
        )
    ).all()

    earned: list[Badge] = []
    for row in rows:
        try:
            definition = REGISTRY.get(row.achievement_key)
        except RegistryError:  # pragma: no cover - the registry validates at load
            continue
        earned.append(
            Badge(
                key=row.achievement_key,
                name=definition.name,
                description=definition.description,
                icon=definition.icon,
                tier=definition.tier,
                points=row.points,
            )
        )
    return tuple(earned)


@router.get("/people/{username}", response_class=HTMLResponse, response_model=None)
async def person_page(
    username: str,
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> HTMLResponse | RedirectResponse:
    """One participant, at the level of detail the viewer is allowed.

    For anyone but the owner and an admin this is streak, points, badges and
    their live notes — the shape and the comedy, not the detail.
    """
    subject = await session.scalar(
        select(User).where(User.username == username.strip().lower())
    )
    if subject is None or not subject.is_active:
        return _templates(request).TemplateResponse(
            request,
            "errors/404.html",
            {"user": user},
            status_code=404,
        )

    year = _year(request, user)
    score = await scoring.score_year(
        session, subject, year, window_minutes=_window(request)
    )
    see_detail = visibility.can_see_detail(user, subject)

    # Notes are published to everyone, including the owner, so they are gathered
    # unconditionally. `see_detail` only governs the finer-grained stuff.
    notes = await published_notes(session, subject.id)

    days: list[visibility.VisibleDay] = []
    if not see_detail:
        qualified_by_day = {d.day: d.qualified for d in score.days}
        rows = (
            await session.scalars(
                select(DailyLog)
                .where(DailyLog.user_id == subject.id)
                .order_by(DailyLog.day.desc())
                .limit(60)
            )
        ).all()
        days = [
            visibility.day_for_others(
                row, qualified=qualified_by_day.get(row.day, False)
            )
            for row in rows
        ]

    return _templates(request).TemplateResponse(
        request,
        "people/person.html",
        {
            "user": user,
            "subject": subject,
            "year": year,
            "score": score,
            "days": days,
            "notes": notes,
            "see_detail": see_detail,
            "badges": await _badges(session, subject.id, year),
            "nav": "people",
            "csrf_token": csrf_token(request),
        },
    )
