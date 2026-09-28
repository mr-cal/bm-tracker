"""The signed-in user's own settings.

The home page lived here while the feed was being built and has moved to
`routes/people.py`, which owns `/`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bm_tracker import forms, theme
from bm_tracker.dependencies import AuthenticatedUser, DbSession, csrf_token
from bm_tracker.services import audit_service, bm_service

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
    return await _settings_page(request, user)


async def _settings_page(
    request: Request,
    user: AuthenticatedUser,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render the settings page.

    Args:
        request: The incoming request.
        user: The signed-in user.
        error: An error message, if any.
        status_code: The status to return, so a rejected change is a 400 rather
            than a 200 that looks like it worked.

    Returns:
        The rendered page.

    """
    return _templates(request).TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "nav": "",
            "csrf_token": csrf_token(request),
            "theme_options": theme.THEME_OPTIONS,
            "saved": request.query_params.get("saved"),
            "error": error,
        },
        status_code=status_code,
    )


@router.post("/settings/name", response_class=HTMLResponse, response_model=None)
async def save_display_name(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> HTMLResponse | RedirectResponse:
    """Change the name other people see this person by.

    The sign-in name is not changeable here: it is the address the account is
    reached at, and changing it would break the links other people have saved.
    """
    form = await request.form()
    forms.guard_csrf(request, form)
    typed = forms.form_text(form, "display_name") or ""
    try:
        stored = await bm_service.set_display_name(session, user, typed)
    except ValueError as exc:
        return await _settings_page(request, user, error=str(exc), status_code=400)

    await audit_service.record(
        session,
        action="user.update",
        user_id=user.id,
        entity_type="user",
        entity_id=str(user.id),
        detail={"field": "display_name"},
    )
    await session.commit()
    return RedirectResponse(f"/settings?saved={stored[:24]}", status_code=303)


@router.post("/settings/theme", response_class=HTMLResponse, response_model=None)
async def save_theme(
    request: Request,
    session: DbSession,
    user: AuthenticatedUser,
) -> RedirectResponse:
    """Record the colour scheme this person wants to see.

    Stored twice on purpose. The database carries the choice to another device;
    the cookie carries it to the sign-in screen, which is painted before anyone
    is signed in and has no user record to read.

    The cookie is set with `samesite=lax` and an explicit expiry rather than a
    session cookie, so the sign-in page is already the right colour after a
    restart, and a link from elsewhere cannot change somebody's setting.
    """
    form = await request.form()
    forms.guard_csrf(request, form)
    choice = theme.parse_theme(forms.form_text(form, "theme"))
    user.theme = choice
    await session.commit()

    response = RedirectResponse("/settings?saved=theme", status_code=303)
    response.set_cookie(
        theme.COOKIE_NAME,
        choice,
        max_age=theme.COOKIE_MAX_AGE,
        samesite="lax",
        path="/",
    )
    return response
