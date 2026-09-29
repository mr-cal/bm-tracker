"""The signed-in user's own dashboard, and the leaderboard.

Both are year-scoped. The year is a viewing convention, not a data boundary:
the export in §5.4 is the one place it is deliberately absent.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bm_tracker import bristol, scoring
from bm_tracker import strain as strain_lib
from bm_tracker.achievements import engine
from bm_tracker.achievements.engine import Status
from bm_tracker.achievements.registry import Achievement
from bm_tracker.dependencies import AuthenticatedUser, DbSession, csrf_token
from bm_tracker.forms import int_arg as _int_arg
from bm_tracker.models import AchievementUnlock, BmEntry, DailyLog, User
from bm_tracker.notes.achievements import NoteAchievement
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
    """Show the collection, tier by tier, earning the right to see each one.

    A tier's names stay hidden until enough points have been earned, because a
    catalogue of 300 revealed on day one is a list of things to grind rather
    than a collection to look at. Within a tier you have unlocked, every
    achievement is listed whatever its state — the absurdity of "Blatherer: ten
    entries in a single day" is the point, and it only works if the name is
    visible.

    An achievement you have earned is always shown, whatever the threshold says.
    Hiding something you already have is just a bug wearing a disguise.
    """
    year = requested_year(request, user)
    statuses = await engine.status_for(
        session,
        user,
        year,
        window_minutes=request.app.state.settings.quick_entry_window_minutes,
    )

    # Ordered by what the tier is worth, not by whatever order the TOML file
    # happened to define them in. Insertion order put the page out as Common,
    # Rare, Uncommon, Legendary — 2, 10, 5, 20 — which reads as nonsense for a
    # collection laid out to be skimmed.
    # Note achievements join the same page, same tiers and same counters, rather
    # than living somewhere of their own. They are earned from a different
    # trigger — reading a note rather than counting a day — but a reader does not
    # care why, and a second list of "things you have earned" would be a worse
    # page than one list of them.
    statuses = [*statuses, *(await _note_statuses(session, user, year))]

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
            "grouped": dict(
                sorted(
                    grouped.items(), key=lambda kv: engine.REGISTRY.tiers.get(kv[0], 0)
                )
            ),
            "earned_count": sum(1 for s in statuses if s.unlocked),
            "earned_points": sum(s.points for s in statuses if s.unlocked),
            "tier_points": engine.REGISTRY.tiers,
            "lifetime_points": await _lifetime_points(
                session,
                user,
                request.app.state.settings.quick_entry_window_minutes,
            ),
            "tier_reveal": engine.REGISTRY.reveal_at,
            "nav": "",
            "csrf_token": csrf_token(request),
        },
    )


async def _note_statuses(session: AsyncSession, user: User, year: int) -> list[Status]:
    """Return the note achievements as statuses the page can render.

    Args:
        session: The session to read through.
        user: Whose collection.
        year: The calendar year.

    Returns:
        One `Status` per note achievement, from the catalogue and the unlock
        table. Built without asking the embedder anything, because the page must
        render whether or not a key is configured.

    """
    from sqlalchemy import select  # noqa: PLC0415

    from bm_tracker.models import AchievementUnlock  # noqa: PLC0415
    from bm_tracker.notes import achievements as note_defs  # noqa: PLC0415
    from bm_tracker.notes import service as note_service  # noqa: PLC0415

    earned = {
        row.achievement_key.removeprefix(note_service.PREFIX): row
        for row in (
            await session.scalars(
                select(AchievementUnlock).where(
                    AchievementUnlock.user_id == user.id,
                    AchievementUnlock.year == year,
                )
            )
        ).all()
        if note_service.is_note_key(row.achievement_key)
    }
    out: list[Status] = []
    for definition in note_defs.load():
        row = earned.get(definition.key)
        out.append(
            Status(
                achievement=_as_achievement(definition),
                unlocked=row is not None,
                unlocked_at=row.unlocked_at if row else None,
                # A note achievement is either found or not, and the search
                # itself was already the work. There is no partial credit for a
                # note that did not say enough, so there is no bar.
                progress=1.0 if row else None,
                current=None,
                target=None,
            )
        )
    return out


def _as_achievement(definition: NoteAchievement) -> Achievement:
    """Return a note definition shaped like a registry achievement.

    The page renders one list, and the two kinds of achievement differ in
    provenance rather than in anything a reader sees. This is the adapter, in
    one place, rather than a conditional in the template.

    Args:
        definition: The note definition.

    Returns:
        An object with the attributes the page reads.

    """
    return Achievement(
        key=definition.key,
        name=definition.name,
        description=definition.description,
        tier=definition.tier,
        icon="default",
        rule=None,
        custom=None,
        points=definition.points,
    )


async def _lifetime_points(session: DbSession, user: User, window_minutes: int) -> int:
    """Return every point a person has ever earned, across all years.

    The reveal thresholds are about how long somebody has been using the app, so
    the comparison cannot be against one calendar year: a person who started in
    December would otherwise unlock a whole year of tiers by January.

    Points are derived rather than stored, so this runs the derivation once per
    year the person has logged. It is one user, once, on the page that needs it.

    Args:
        session: The session to read through.
        user: Whose points to total.
        window_minutes: The quick-entry window, so the derivation matches.

    Returns:
        Logging points for every year, plus achievement points ever unlocked.

    """
    years = (
        await session.scalars(
            select(func.strftime("%Y", DailyLog.day))
            .where(DailyLog.user_id == user.id)
            .distinct()
        )
    ).all()

    logging = 0
    for year in (int(y) for y in years if y):
        score = await scoring.score_year(
            session, user, year, window_minutes=window_minutes
        )
        logging += score.logging_points

    unlocked = await session.scalar(
        select(func.coalesce(func.sum(AchievementUnlock.points), 0)).where(
            AchievementUnlock.user_id == user.id
        )
    )
    return logging + int(unlocked or 0)


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
    # One query for everybody's achievement points in the year, so the rank can
    # be a single number rather than two standings that never quite add up.
    earned_rows = (
        await session.execute(
            select(AchievementUnlock.user_id, func.sum(AchievementUnlock.points))
            .where(AchievementUnlock.year == year)
            .group_by(AchievementUnlock.user_id)
        )
    ).all()
    earned = {uid: int(total or 0) for uid, total in earned_rows}
    # `rank` yields (User, UserScore) pairs, already ordered best-first.
    ordered = scoring.rank(scores, {u.id: u for u in users}, achievement_points=earned)

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
                    "achievement_points": earned.get(person.id, 0),
                    "total": score.logging_points + earned.get(person.id, 0),
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
