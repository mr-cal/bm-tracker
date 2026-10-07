"""Inline SVG icons for the templates.

The icon files are read once per process and their markup is inlined into the
page, rather than referenced with `<use href="...#id">` or `<img src="...">`.
Both of those were tried and neither is right here: `<use>` against an external
file needs every symbol to carry an id, and `<img>` cannot inherit
`currentColor`, so an active tab and an inactive one would be the same colour.

Inlining costs one small string per icon per render and gives real cascade
support, which is the whole reason the icons are SVG rather than emoji.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from markupsafe import Markup

ICON_DIR = Path(__file__).parent / "static" / "img" / "ui"

# The class list an icon may be given, and whether a name is one we have. Both
# are checked at call time so a typo fails loudly in development rather than
# rendering an empty box in production.
_EXTRA_CLASSES = frozenset(
    {
        "app-drawer-toggle__glyph",
        "app-topbar__flame",
        "app-tab__glyph",
        "date-field__icon",
        "input-icon",
        "app-drawer__glyph",
        "pick__icon",
        "tile__glyph",
    }
)


class UnknownIconError(KeyError):
    """Raised when a template asks for an icon that does not exist."""


@cache
def markup(name: str) -> str:
    """Return the inline SVG for an icon.

    Args:
        name: The icon name, without the `.svg` suffix.

    Returns:
        The file's contents, whitespace-collapsed.

    Raises:
        UnknownIconError: If there is no such icon.

    """
    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        raise UnknownIconError(f"no icon named {name!r} in {ICON_DIR}")
    return " ".join(path.read_text().split())


def icon(name: str, extra_class: str = "") -> str:
    """Return an icon as inline SVG with a class on it.

    Args:
        name: The icon name, without the `.svg` suffix.
        extra_class: Extra classes for the element. Checked against an allowlist
            so a template cannot smuggle markup in through this argument.

    Returns:
        The `<svg>` element, as safe markup.

    Raises:
        UnknownIconError: If the name is not an icon, or the class is not allowed.

    """
    for candidate in extra_class.split():
        if candidate not in _EXTRA_CLASSES:
            msg = f"{candidate!r} is not an allowed icon class"
            raise UnknownIconError(msg)
    body = markup(name)
    if extra_class:
        body = body.replace('class="ico"', f'class="ico {extra_class}"', 1)
    # Markup, so Jinja's autoescaping does not turn the element into visible
    # text. Without this the whole SVG renders as a string of angle brackets:
    # unbreakable, and about 4800px wide on a 390px screen.
    return Markup(body)


BADGE_ICON_DIR = Path(__file__).parent / "static" / "img" / "badges"

# The class list a badge may be given. Same rule as `icon`: checked at
# call time so a typo fails loudly rather than rendering an unsized icon.
_BADGE_EXTRA_CLASSES = frozenset(
    {
        "achievement-tile__glyph",
        "achievement-tile__glyph--hidden",
        "achievement-tile__glyph--locked",
        "reward__award-icon",
    }
)


@cache
def badge_markup(name: str) -> str:
    """Return the inline SVG for a badge icon.

    Args:
        name: The badge name, without the `.svg` suffix.

    Returns:
        The file's contents, whitespace-collapsed.

    Raises:
        UnknownIconError: If there is no such badge.

    """
    path = BADGE_ICON_DIR / f"{name}.svg"
    if not path.is_file():
        raise UnknownIconError(f"no badge named {name!r} in {BADGE_ICON_DIR}")
    return " ".join(path.read_text().split())


def badge_icon(name: str, extra_class: str = "") -> str:
    """Return a badge as inline SVG with a class on it.

    The badge files, unlike the UI icons, carry no class of their own,
    so the class is injected into the `<svg>` tag rather than replacing
    one that is already there. Inlined rather than referenced for the
    same reason the UI icons are: a referenced SVG's `currentColor`
    resolves to black, which is a badge that says nothing on a dark
    card.

    Args:
        name: The badge name, without the `.svg` suffix.
        extra_class: Extra classes for the element. Checked against an
            allowlist so a template cannot smuggle markup in through
            this argument.

    Returns:
        The `<svg>` element, as safe markup.

    Raises:
        UnknownIconError: If the name is not a badge, or the class is
            not allowed.

    """
    for candidate in extra_class.split():
        if candidate not in _BADGE_EXTRA_CLASSES:
            msg = f"{candidate!r} is not an allowed badge class"
            raise UnknownIconError(msg)
    body = badge_markup(name)
    if extra_class:
        body = body.replace("<svg ", f'<svg class="{extra_class}" ', 1)
    # Markup, for the same reason as `icon`: autoescaping would turn
    # the element into a line of visible angle brackets.
    return Markup(body)
