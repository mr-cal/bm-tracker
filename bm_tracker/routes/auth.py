"""Sign-in, sign-out and setup-link routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bm_tracker.dependencies import (
    CSRF_FIELD_NAME,
    CurrentUser,
    DbSession,
    csrf_token,
    sign_in,
    sign_out,
    verify_csrf,
)
from bm_tracker.services import auth_service, invite_service

if TYPE_CHECKING:
    from bm_tracker.models import User

router = APIRouter(tags=["auth"])


def _templates(request: Request) -> Jinja2Templates:
    """Return the app's template environment.

    Args:
        request: The incoming request.

    Returns:
        The configured `Jinja2Templates`.

    """
    templates: Jinja2Templates = request.app.state.templates
    return templates


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login_form(
    request: Request, user: CurrentUser
) -> HTMLResponse | RedirectResponse:
    """Show the sign-in form, or bounce an already-signed-in user home."""
    if user is not None:
        return RedirectResponse("/", status_code=303)
    templates = _templates(request)
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"csrf_token": csrf_token(request), "error": None},
    )


@router.post("/login", response_class=HTMLResponse, response_model=None)
async def login_submit(
    request: Request,
    session: DbSession,
) -> HTMLResponse | RedirectResponse:
    """Verify credentials and establish a session."""
    templates = _templates(request)
    form = await request.form()
    token = str(form.get(CSRF_FIELD_NAME, ""))

    try:
        verify_csrf(request, token)
    except HTTPException:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {
                "csrf_token": csrf_token(request),
                "error": "Your session expired. Try again.",
            },
            status_code=403,
        )

    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    client_ip = request.client.host if request.client else ""

    try:
        signed_in = await auth_service.authenticate(
            session, username, password, client_ip=client_ip
        )
    except auth_service.AuthenticationError as exc:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"csrf_token": csrf_token(request), "error": str(exc)},
            status_code=401,
        )

    sign_in(request, signed_in)
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Clear the session.

    POST-only: a GET logout can be triggered by any image tag on a page, which
    would let a third party sign somebody out.
    """
    sign_out(request)
    return RedirectResponse("/login", status_code=303)


@router.get("/setup/{token}", response_class=HTMLResponse, response_model=None)
async def setup_form(request: Request, token: str, session: DbSession) -> HTMLResponse:
    """Show the password form for a setup link, or explain why it cannot."""
    templates = _templates(request)
    try:
        await invite_service.find_valid(session, token)
    except invite_service.InvalidInviteError as exc:
        return templates.TemplateResponse(
            request,
            "auth/setup.html",
            {"csrf_token": csrf_token(request), "error": str(exc), "token": None},
            status_code=410,
        )
    return templates.TemplateResponse(
        request,
        "auth/setup.html",
        {"csrf_token": csrf_token(request), "error": None, "token": token},
    )


@router.post("/setup/{token}", response_class=HTMLResponse, response_model=None)
async def setup_submit(
    request: Request,
    token: str,
    session: DbSession,
) -> HTMLResponse | RedirectResponse:
    """Redeem a setup link and sign the new user in."""
    templates = _templates(request)
    form = await request.form()
    csrf = str(form.get(CSRF_FIELD_NAME, ""))
    password = str(form.get("password", ""))
    confirm = str(form.get("confirm_password", ""))

    try:
        verify_csrf(request, csrf)
    except HTTPException:
        return templates.TemplateResponse(
            request,
            "auth/setup.html",
            {
                "csrf_token": csrf_token(request),
                "error": "Your session expired. Try again.",
                "token": token,
            },
            status_code=403,
        )

    if password != confirm:
        return templates.TemplateResponse(
            request,
            "auth/setup.html",
            {
                "csrf_token": csrf_token(request),
                "error": "The passwords did not match.",
                "token": token,
            },
            status_code=400,
        )

    try:
        user: User = await invite_service.redeem(session, token, password)
    except invite_service.InvalidInviteError as exc:
        await session.rollback()
        return templates.TemplateResponse(
            request,
            "auth/setup.html",
            {"csrf_token": csrf_token(request), "error": str(exc), "token": None},
            status_code=410,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "auth/setup.html",
            {"csrf_token": csrf_token(request), "error": str(exc), "token": token},
            status_code=400,
        )

    await session.commit()
    sign_in(request, user)
    return RedirectResponse("/", status_code=303)
