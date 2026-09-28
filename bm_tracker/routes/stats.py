"""The signed-in user's own dashboard, and the leaderboard.

Both are year-scoped. The year is a viewing convention, not a data boundary:
the export in §5.4 is the one place it is deliberately absent.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from bm_tracker import bristol, scoring
from bm_tracker import strain as strain_lib
from bm_tracker.achievements import engine
from bm_tracker.dependencies import AuthenticatedUser, DbSession, csrf_token
from bm_tracker.forms import int_arg as _int_arg
from bm_tracker.models import BmEntry, DailyLog, User
from bm_tracker.timezones import now_in, year_bounds

router = APIRouter(tags=["stats"])

# How many entries the dashboard previews, and how many the full table shows.
RECENT_ENTRIES = 10
ENTRIES_PER_PAGE = 30

SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24


def _templates(request: Request) -> Jinja2Templates:
    """Return the app's template environment.

    Args:
        request: The incoming request.

    Returns:
        The configured `Jinja2Templates`.

    """
    templates: Jinja2Templates = request.app.state.templates
    return templates


def requested_year(request: Request, user: AuthenticatedUser) -> int:
    """Return the year being viewed, defaulting to the user's current year.

    Args:
        request: The incoming request.
        user: The authenticated user, for the default.

    Returns:
        The calendar year.

    """
    raw = request.query_params.get("year", "")
    current, _ = now_in(user.timezone)
    if raw.isdigit():
        return int(raw)
    return current.year


async def available_years(session: DbSession, user: AuthenticatedUser) -> list[int]:
    """Return the years the user has data in, newest first.

    Args:
        session: The session to read through.
        user: The owner.

    Returns:
        The years, which the selector offers.

    """
    rows = (
        await session.scalars(
            select(func.strftime("%Y", DailyLog.day)).where(DailyLog.user_id == user.id)
        )
    ).all()
    return sorted({int(value) for value in rows if value}, reverse=True)


@router.get("/dashboard", response_class=HTMLResponse, response_model=None)
async def dashboard(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> HTMLResponse:
    """Show the user's own year: streak, points, and what they logged.

    Args:
        request: The incoming request.
        session: The database session.
        user: The authenticated user.

    Returns:
        The rendered page.

    """
    year = requested_year(request, user)
    score = await scoring.score_year(
        session,
        user,
        year,
        window_minutes=request.app.state.settings.quick_entry_window_minutes,
    )
    local_today, _ = now_in(user.timezone)

    distribution = dict.fromkeys(range(bristol.BRISTOL_MIN, bristol.BRISTOL_MAX + 1), 0)
    entries: list[BmEntry] = []
    start, end = year_bounds(year)
    if score.days:
        rows = (
            await session.scalars(
                select(BmEntry)
                .join(DailyLog, DailyLog.id == BmEntry.daily_log_id)
                .where(
                    DailyLog.user_id == user.id,
                    DailyLog.day >= start,
                    DailyLog.day <= end,
                )
                .order_by(DailyLog.day.desc(), BmEntry.occurred_local.desc())
                .limit(20)
            )
        ).all()
        entries = list(rows)
        for entry in (
            await session.scalars(
                select(BmEntry)
                .join(DailyLog, DailyLog.id == BmEntry.daily_log_id)
                .where(
                    DailyLog.user_id == user.id,
                    DailyLog.day >= start,
                    DailyLog.day <= end,
                )
            )
        ).all():
            distribution[entry.bristol_type] += 1

    # Bars are drawn as a share of the *busiest* type rather than as a multiple
    # of the raw count. Widths are then always 0-100%, so the chart cannot push
    # the page sideways however many of one type someone logs.
    busiest = max(distribution.values(), default=0)
    bar_pct = {
        value: (0 if busiest == 0 else round(count / busiest * 100))
        for value, count in distribution.items()
    }
    return _templates(request).TemplateResponse(
        request,
        "dashboard/index.html",
        {
            "user": user,
            "year": year,
            "today": local_today,
            "years": await available_years(session, user),
            "score": score,
            "distribution": distribution,
            "bar_pct": bar_pct,
            "bristol_scale": bristol.BRISTOL_SCALE,
            "bristol_by_value": {t.value: t for t in bristol.BRISTOL_SCALE},
            "recent": entries,
            "nav": "",
            "csrf_token": csrf_token(request),
        },
    )


@router.get("/achievements", response_class=HTMLResponse, response_model=None)
async def achievements_page(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> HTMLResponse:
    """Show the whole collection, earned and not, with progress on the rest.

    Every achievement is listed. With 300 coming and most unlikely for anyone, a
    wall of locked icons with no names is duller than one that says "Blatherer:
    ten in a single day" — the absurdity is the point.
    """
    year = requested_year(request, user)
    statuses = await engine.status_for(
        session,
        user,
        year,
        window_minutes=request.app.state.settings.quick_entry_window_minutes,
    )

    grouped: dict[str, list] = {}
    for status in statuses:
        grouped.setdefault(status.achievement.tier, []).append(status)

    return _templates(request).TemplateResponse(
        request,
        "achievements/index.html",
        {
            "user": user,
            "year": year,
            "statuses": statuses,
            "grouped": grouped,
            "earned_count": sum(1 for s in statuses if s.unlocked),
            "earned_points": sum(s.points for s in statuses if s.unlocked),
            "tier_points": engine.REGISTRY.tiers,
            "nav": "",
            "csrf_token": csrf_token(request),
        },
    )


@router.get("/leaderboard", response_class=HTMLResponse, response_model=None)
async def leaderboard(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> HTMLResponse:
    """Show everyone's standing for the year.

    Sorted by logging points, so achievement points cannot reorder the board.

    Args:
        request: The incoming request.
        session: The database session.
        user: The authenticated user.

    Returns:
        The rendered page.

    """
    year = requested_year(request, user)
    users = list(
        (
            await session.scalars(
                select(User).where(User.is_active.is_(True)).order_by(User.username)
            )
        ).all()
    )
    window = request.app.state.settings.quick_entry_window_minutes
    scores = await scoring.score_all_users(session, users, year, window_minutes=window)
    # `rank` yields (User, UserScore) pairs, already ordered best-first.
    ordered = scoring.rank(scores, {u.id: u for u in users})

    return _templates(request).TemplateResponse(
        request,
        "leaderboard/index.html",
        {
            "user": user,
            "year": year,
            "today": now_in(user.timezone)[0],
            "nav": "board",
            "rows": [
                {
                    "rank": index + 1,
                    "person": person,
                    "score": score,
                    "is_you": person.id == user.id,
                }
                for index, (person, score) in enumerate(ordered)
            ],
            "csrf_token": csrf_token(request),
        },
    )


@router.get("/dashboard/entries", response_class=HTMLResponse, response_model=None)
async def dashboard_entries(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> HTMLResponse:
    """Show every entry the user has logged, newest first, thirty to a page.

    The dashboard previews a handful because nobody wants a year of BMs in the
    summary; this is where the rest of them live. It is scoped to the owner, so
    unlike the group surfaces it needs no visibility check.

    Args:
        request: The incoming request.
        session: The database session.
        user: The authenticated user.

    Returns:
        The rendered page.

    """
    year = requested_year(request, user)
    start, end = year_bounds(year)

    page = max(1, _int_arg(request.query_params.get("page"), 1))
    condition = (
        DailyLog.user_id == user.id,
        DailyLog.day >= start,
        DailyLog.day <= end,
    )

    total = (
        await session.scalar(
            select(func.count())
            .select_from(BmEntry)
            .join(DailyLog, DailyLog.id == BmEntry.daily_log_id)
            .where(*condition)
        )
    ) or 0
    pages = max(1, -(-total // ENTRIES_PER_PAGE))

    # A page number past the end lands on the last real page rather than an
    # empty one, so a stale bookmark still shows something.
    page = min(page, pages)
    rows = (
        await session.scalars(
            select(BmEntry)
            .join(DailyLog, DailyLog.id == BmEntry.daily_log_id)
            .where(*condition)
            .order_by(DailyLog.day.desc(), BmEntry.occurred_local.desc())
            .offset((page - 1) * ENTRIES_PER_PAGE)
            .limit(ENTRIES_PER_PAGE)
        )
    ).all()

    return _templates(request).TemplateResponse(
        request,
        "dashboard/entries.html",
        {
            "user": user,
            "year": year,
            "years": await available_years(session, user),
            "entries": rows,
            "bristol_by_value": {t.value: t for t in bristol.BRISTOL_SCALE},
            "strain_by_value": {s.value: s for s in strain_lib.STRAIN_SCALE},
            "page": page,
            "pages": pages,
            "total": total,
            "per_page": ENTRIES_PER_PAGE,
            "nav": "",
            "csrf_token": csrf_token(request),
        },
    )
