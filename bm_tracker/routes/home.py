"""The signed-in user's own settings.

The home page lived here while the feed was being built and has moved to
`routes/people.py`, which owns `/`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from bm_tracker.dependencies import AuthenticatedUser, csrf_token

router = APIRouter(tags=["home"])


def _templates(request: Request) -> Jinja2Templates:
    """Return the app's template environment.

    Args:
        request: The incoming request.

    Returns:
        The configured `Jinja2Templates`.

    """
    templates: Jinja2Templates = request.app.state.templates
    return templates


@router.get("/help", response_class=HTMLResponse, response_model=None)
async def help_page(request: Request, user: AuthenticatedUser) -> HTMLResponse:
    """Explain the scoring, rendered from the live constants.

    The numbers come from `scoring`, not from prose, so the page cannot drift out
    of date with the rules: retune a constant and the explanation changes with
    it. A test asserts every constant appears on the page.
    """
    from bm_tracker import scoring  # noqa: PLC0415
    from bm_tracker.achievements import engine  # noqa: PLC0415

    base = scoring.POINTS_PER_QUALIFYING_DAY
    cap = scoring.STREAK_BONUS_STEP * scoring.STREAK_BONUS_MAX_STEPS

    return _templates(request).TemplateResponse(
        request,
        "help.html",
        {
            "user": user,
            "nav": "",
            "csrf_token": csrf_token(request),
            "constants": {
                "day_points": base,
                "streak_max": cap,
                "note_points": scoring.POINTS_NOTE,
                "quick_points": scoring.POINTS_QUICK_ENTRY,
                "backfill_points": scoring.POINTS_BACKFILLED_DAY,
                "quick_window": request.app.state.settings.quick_entry_window_minutes,
                "tier_points": min(engine.REGISTRY.tiers.values()),
                "achievement_count": len(engine.REGISTRY),
            },
            # From `scoring`, not hand-rolled: the worked example cannot
            # disagree with the rules it is explaining.
            "worked_total": scoring.total_for_run(5),
            "week_total": scoring.total_for_run(7),
            "year_total": f"{scoring.total_for_run(365):,}",
        },
    )


@router.get("/settings", response_class=HTMLResponse, response_model=None)
async def settings_page(request: Request, user: AuthenticatedUser) -> HTMLResponse:
    """Show the signed-in user's own settings.

    Args:
        request: The incoming request.
        user: The authenticated user.

    Returns:
        The rendered page.

    """
    return _templates(request).TemplateResponse(
        request,
        "settings.html",
        {"user": user, "nav": "", "csrf_token": csrf_token(request)},
    )
