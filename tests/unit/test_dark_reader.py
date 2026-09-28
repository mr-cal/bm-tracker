"""Tests that the stylesheet will not fight a reader-mode extension.

Dark Reader and its relatives darken a page by inverting what the page serves:
`html { filter: invert(1) hue-rotate(180deg) }`, or, in the smarter modes, by
parsing the CSS and rewriting the colours they can classify. Both approaches are
brittle in ways this app can control, and the failure mode is a page that is
half-inverted and unreadable.

These are static checks on the stylesheet rather than browser tests, because the
things that break an extension are all visible in the CSS.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = (
    Path(__file__).resolve().parent.parent.parent
    / "bm_tracker"
    / "static"
    / "css"
    / "custom.css"
)

# Properties that make an extension's job harder or its output wrong.
# `filter` and `backdrop-filter` on an ancestor create a containing block and
# double-invert; a background image is painted in colours the extension cannot
# see; a blend mode composites against whatever is beneath it.
HAZARDS = ("filter", "backdrop-filter", "mix-blend-mode", "background-image")


def _rules() -> str:
    return CSS.read_text()


@pytest.mark.parametrize("hazard", HAZARDS)
def test_the_hazard_is_only_ever_used_where_it_is_safe(hazard: str) -> None:
    """No hazard on `:root`, `html` or `body`.

    An extension inverts the root. A filter on the root is inverted twice and
    comes out unchanged; a filter on a descendant is inverted once and behaves as
    the extension expects.
    """
    css = _rules()
    for selector in (":root", "html", "body"):
        # A rule whose selector list contains one of these three.
        for match in re.finditer(
            rf"(?m)^([^{{}}]*\b{re.escape(selector)}\b[^{{}}]*)\{{([^}}]*)\}}", css
        ):
            body = match.group(2)
            if re.search(rf"(?<![\w-]){re.escape(hazard)}\s*:", body):
                value = re.search(rf"(?<![\w-]){re.escape(hazard)}\s*:\s*([^;]+)", body)
                if value and value.group(1).strip() not in {"none", "normal"}:
                    pytest.fail(
                        f"{selector} sets {hazard}: {value.group(1).strip()!r}. "
                        "A reader-mode extension inverts the root, so a filter "
                        "there is inverted twice and has no effect, or a "
                        "background image is painted in colours it cannot see."
                    )


def test_the_root_declares_its_palette_as_variables() -> None:
    """Every accent is a token, so a parser can classify and override it.

    A page carrying a couple of dozen inline rgba() values is a page whose
    colours get guessed at. A custom property is the easiest thing there is to
    resolve, and it is also what makes the whole palette changeable in one place.
    """
    css = _rules()
    root_block = re.search(r"(?ms)^:root\s*\{(.*?)\}", css)
    assert root_block, "there is no :root block defining the palette"
    assert "--bm-" in root_block.group(1)

    # Colours outside the token blocks mean something bypassed the palette.
    outside = re.sub(r'(?ms)^(:root|\[data-bs-theme="dark"\])\s*\{[^}]*\}', "", css)

    offenders: list[str] = []
    # Track which rule each declaration belongs to: the swatch is a picture of
    # the other two themes, so it has to stay literal, and the selector is on a
    # different line from the colour.
    selector = ""
    in_swatch = False
    for line in outside.splitlines():
        stripped = line.strip()
        if stripped.endswith("{"):
            selector = stripped
            in_swatch = "theme-swatch" in selector
        if re.search(r"#[0-9a-fA-F]{3,8}\b", line) and not in_swatch:
            offenders.append(f"{selector} -> {stripped}")
    assert not offenders, f"colours outside the palette: {offenders}"


def test_icons_inherit_the_text_colour() -> None:
    """Every icon is stroked with `currentColor`, so an inversion carries it.

    An icon with a fixed colour is inverted to its complement while the text
    around it is inverted back, which is how an icon ends up invisible.
    """
    icons = (
        Path(__file__).resolve().parent.parent.parent / "bm_tracker" / "static" / "img"
    )
    files = list(icons.rglob("*.svg"))
    assert files, "no icons to check"
    for path in files:
        body = path.read_text()
        assert 'stroke="currentColor"' in body, f"{path.name} has a fixed stroke"
        assert "#" not in body.split("stroke=", 1)[1][:40], (
            f"{path.name} has a hex colour"
        )


def test_no_token_defines_itself() -> None:
    """`--bm-warn: var(--bm-warn)` is invalid, and silently so.

    A custom property that refers to itself in its own definition resolves to
    the guaranteed-invalid value, and every property that used it falls back to
    its initial value — no error, no warning, just a colour that silently
    stopped applying. Five of them were written that way by a blanket
    find-and-replace during the tokenising pass.
    """
    css = _rules()
    circular = re.findall(r"(--bm-[a-z-]+):\s*var\((--bm-[a-z-]+)\)", css)

    offenders = [name for name, ref in circular if name == ref]
    assert not offenders, f"tokens that define themselves: {offenders}"


def test_every_token_used_is_defined_in_both_themes() -> None:
    """A token used in the stylesheet must resolve in light *and* dark.

    A `--bm-warn` that only exists under `[data-bs-theme="dark"]` is not a dark
    accent, it is an invisible declaration in the light theme.
    """
    css = _rules()
    used = set(re.findall(r"var\((--bm-[a-z-]+)", css))
    assert used, "no tokens in use at all"

    light = re.search(r"(?ms)^:root\s*\{(.*?)^\}", css)
    dark = re.search(r'(?ms)^\[data-bs-theme="dark"\]\s*\{(.*?)^\}', css)
    assert light, "no light theme block"
    assert dark, "no dark theme block"

    for block, name in ((light.group(1), "light"), (dark.group(1), "dark")):
        defined = set(re.findall(r"(--bm-[a-z-]+):", block))
        missing = used - defined
        assert not missing, f"{name} theme does not define: {sorted(missing)}"
