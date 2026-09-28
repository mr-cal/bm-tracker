"""Tests for the colour scheme.

The three that matter are the default, the parse, and the fact that `auto` is
the only value that keeps listening to the system.
"""

from __future__ import annotations

import pytest
from bm_tracker import theme


def test_light_is_the_default() -> None:
    """Nobody is put in a dark theme they did not ask for."""
    assert theme.DEFAULT_THEME == theme.LIGHT
    assert theme.parse_theme(None) == theme.LIGHT
    assert theme.parse_theme("") == theme.LIGHT
    assert theme.parse_theme("   ") == theme.LIGHT


def test_there_are_exactly_three_choices() -> None:
    assert [o.value for o in theme.THEME_OPTIONS] == ["light", "dark", "auto"]
    assert {"light", "dark", "auto"} == theme.THEMES


@pytest.mark.parametrize("value", ["light", "dark", "auto"])
def test_a_real_choice_survives(value: str) -> None:
    assert theme.parse_theme(value) == value


@pytest.mark.parametrize("value", ["LIGHT", "  dark  ", "Auto"])
def test_case_and_whitespace_are_forgiven(value: str) -> None:
    """A hand-edited form should not silently reset somebody to light."""
    assert theme.parse_theme(value) == value.lower().strip()


@pytest.mark.parametrize("value", ["sepia", "true", "0", "light dark", "<script>"])
def test_anything_else_is_the_default(value: str) -> None:
    """Nonsense falls back rather than reaching the database."""
    assert theme.parse_theme(value) == theme.LIGHT
    assert not theme.is_valid_theme(value)


def test_the_cookie_is_not_a_session_cookie() -> None:
    """It has to survive a restart, or the sign-in page is the wrong colour."""
    assert theme.COOKIE_MAX_AGE > 60 * 60 * 24
