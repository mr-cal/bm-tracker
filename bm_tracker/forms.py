"""Reading values out of a submitted form.

Starlette types a form value as `str | UploadFile`, so every read needs
coercing before it can be used as text. Doing that in one place keeps the
coercion out of the handlers, and means an unexpected file upload becomes an
empty string rather than an `AttributeError` on `.strip()`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from fastapi import HTTPException, Request, status

from bm_tracker.dependencies import CSRF_FIELD_NAME, CSRF_HEADER_NAME, verify_csrf

if TYPE_CHECKING:
    from starlette.datastructures import FormData

MAX_TEXT_LENGTH = 2000

NOT_FOUND_MESSAGE: Final = "That form field was missing."
CSRF_MESSAGE: Final = "Your session expired. Reload the page and try again."


def form_str(form: FormData, name: str) -> str | None:
    """Return a form field as text, or `None` when absent or empty.

    Args:
        form: The submitted form.
        name: The field name.

    Returns:
        The trimmed value, or `None`.

    """
    raw = form.get(name)
    if raw is None or not isinstance(raw, str):
        return None
    trimmed = raw.strip()
    return trimmed or None


def form_text(form: FormData, name: str) -> str | None:
    """Return a form field as text, preserving internal and trailing newlines.

    For free text like a note, where stripping the whole value would mangle a
    deliberate trailing space or paragraph break.

    Args:
        form: The submitted form.
        name: The field name.

    Returns:
        The value, or `None` when absent or entirely whitespace.

    """
    raw = form.get(name)
    if raw is None or not isinstance(raw, str):
        return None
    if not raw.strip():
        return None
    return raw[:MAX_TEXT_LENGTH]


def form_list(form: FormData, name: str) -> list[str]:
    """Return every value submitted for a repeated field.

    Args:
        form: The submitted form.
        name: The field name.

    Returns:
        The string values, which may be empty.

    """
    return [value for value in form.getlist(name) if isinstance(value, str)]


def form_flag(form: FormData, name: str) -> bool:
    """Return whether a checkbox was ticked.

    Args:
        form: The submitted form.
        name: The field name.

    Returns:
        Whether the flag is present.

    """
    return form.get(name) == "on"


def csrf_from(request: Request, form: FormData) -> str:
    """Return the submitted CSRF token, preferring the header.

    HTMX sends the header, so a partial swap does not have to carry and reparse
    the whole form. A plain form post carries the hidden field instead.

    Args:
        request: The incoming request.
        form: The submitted form.

    Returns:
        The token, or an empty string.

    """
    header = request.headers.get(CSRF_HEADER_NAME)
    if header:
        return header
    return form_str(form, CSRF_FIELD_NAME) or ""


def guard_csrf(request: Request, form: FormData) -> None:
    """Reject a submission without a valid CSRF token.

    Args:
        request: The incoming request.
        form: The submitted form.

    Raises:
        HTTPException: 403 when the token is missing or wrong.

    """
    verify_csrf(request, csrf_from(request, form))


def guard_field(form: FormData, name: str) -> str:
    """Return a required form field.

    Args:
        form: The submitted form.
        name: The field name.

    Returns:
        The value.

    Raises:
        HTTPException: 400 when the field is missing.

    """
    value = form_str(form, name)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=NOT_FOUND_MESSAGE
        )
    return value


def int_arg(raw: str | None, fallback: int) -> int:
    """Return a query argument as a positive int, or the fallback.

    A page number off the end of the range is a stale bookmark, not an error,
    so this never raises: it returns the fallback rather than a 500.

    Args:
        raw: The raw query value.
        fallback: What to use when it is missing, unparseable or not positive.

    Returns:
        The parsed value, or `fallback`.

    """
    try:
        value = int(raw) if raw is not None else fallback
    except ValueError:
        return fallback
    return value if value > 0 else fallback
