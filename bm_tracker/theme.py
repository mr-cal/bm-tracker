"""The colour theme a person sees the app in.

Three choices: light, dark, and auto — auto following the operating system.

Light is the default, and that is a deliberate decision rather than a default
that happened. Two reasons:

* Nobody has to be in a dark theme they did not ask for. A site that opens in
  dark mode because the phone is in dark mode is making a choice on the user's
  behalf, and a light site in a dark room is a legitimate preference.
* A reader-mode extension that darkens pages — Dark Reader and its relatives —
  works by inverting whatever the page serves. Served light, this app inverts
  cleanly. Served dark, the extension usually detects the site is already dark
  and declines to touch it, so the person gets a half-darkened page or none at
  all.

`auto` exists for the case where following the system is genuinely what someone
wants, and it is the one setting that has to keep listening: the preference
media query changes while the tab is open, and `light` and `dark` deliberately
do not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

LIGHT: Final = "light"
DARK: Final = "dark"
AUTO: Final = "auto"

# The cookie is what the page's inline script reads, because it is available
# before sign-in and survives a reload on the login screen. The database is
# what carries the choice to another device.
COOKIE_NAME: Final = "bm_theme"
# Long enough to outlive a phone, short enough that a change is not a relic.
COOKIE_MAX_AGE: Final = 365 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class ThemeOption:
    """One choice in the picker."""

    value: str
    label: str
    hint: str


THEME_OPTIONS: Final[tuple[ThemeOption, ...]] = (
    ThemeOption(LIGHT, "Light", "Always light."),
    ThemeOption(DARK, "Dark", "Always dark."),
    ThemeOption(AUTO, "Auto", "Follow the system."),
)

THEMES: Final[frozenset[str]] = frozenset({LIGHT, DARK, AUTO})
DEFAULT_THEME: Final = LIGHT


def parse_theme(raw: str | None) -> str:
    """Return a submitted theme, or the default.

    An empty submission is the default rather than an error: a form that is
    rendered with nothing preselected is a form whose value is not a choice.

    Args:
        raw: The raw form value.

    Returns:
        One of `light`, `dark` or `auto`.

    """
    if raw is None:
        return DEFAULT_THEME
    value = raw.strip().lower()
    return value if value in THEMES else DEFAULT_THEME


def is_valid_theme(value: str) -> bool:
    """Return whether a string names a theme.

    Args:
        value: The candidate.

    Returns:
        Whether it is one of the three.

    """
    return value in THEMES
