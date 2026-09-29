"""Tests for the achievement icon set.

These exist because of a specific failure. The previous set had 43 files for
120 achievements, two pairs of which were byte-identical SVGs under different
names, and five of them were flames. Every check that did not involve looking at
the pictures passed: the registry resolved every name, the loader verified every
file existed, and the tests counted them. A wall of identical question marks is
not something a test asserts against.

So the invariants that can be checked mechanically are checked here, and
`tools/icons/sheet.py` covers the rest by putting all of them on one grid.

A note on what is *not* asserted: nothing here renders a pixel. Two icons can
have completely different path data and still be indistinguishable at 40px —
that is the class of bug these tests are aimed at, and only a pair of eyes close
it. This file is the cheap half.
"""

from __future__ import annotations

import re
from pathlib import Path

from bm_tracker.achievements import registry
from bm_tracker.notes import achievements as note_achievements
from tools.icons import source
from tools.icons.icons import ICONS, NOTE_ICONS

BADGES = Path(__file__).resolve().parents[2] / "bm_tracker/static/img/badges"
SOURCE = Path(__file__).resolve().parents[2] / "tools/icons/icons.py"


def _geometry() -> dict[str, str]:
    """Return the icon source as written, keyed by achievement.

    Returns:
        The geometry for every icon.

    """
    text = SOURCE.read_text(encoding="utf-8")
    return dict(re.findall(r'^\s{4}"([a-z_0-9]+)":\s*"(.*)",$', text, re.M))


def test_every_achievement_has_its_own_icon() -> None:
    """One drawing per achievement, and no two entries sharing a file.

    This is the invariant the whole exercise was for. Shared icons are how the
    set ended up with five flames and two pairs of identical files, and a
    collection page is something you look at, so two entries that look the same
    are two entries you cannot tell apart.
    """
    icons = [a.icon for a in registry.load().achievements]

    assert len(icons) == len(set(icons)), "two achievements share an icon"
    assert all(a.icon == a.key for a in registry.load().achievements), (
        "an achievement's icon should be named after it, so adding one is one "
        "TOML line and one drawing"
    )


def test_no_two_icons_have_the_same_geometry() -> None:
    """Byte-identical path data under two names is the bug that started this."""
    seen: dict[str, str] = {}
    for key, geometry in _geometry().items():
        normalised = re.sub(r"\s+", " ", geometry)
        assert seen.setdefault(normalised, key) == key, (
            f"{key} has the same drawing as {seen[normalised]}"
        )


def test_every_icon_file_exists_and_nothing_else_does() -> None:
    """The directory and the catalogue are the same set, exactly.

    An icon file for an achievement that no longer exists is dead weight that
    looks like content; a missing one is a 404 on somebody's collection page.
    """
    drawn = {p.stem for p in BADGES.glob("*.svg")}
    # Both catalogues. The note achievements keep their icons in the same
    # directory, so checking only the registry's half would call every one of
    # them a stale file.
    catalogued = {a.icon for a in registry.load().achievements} | {
        a.key for a in note_achievements.load()
    }

    assert drawn == catalogued, (
        f"only on disk: {sorted(drawn - catalogued)}; "
        f"only in a catalogue: {sorted(catalogued - drawn)}"
    )


def test_every_icon_is_valid_and_leaves_the_margin() -> None:
    """Well-formed, on the house grid, and not drawn into the edge.

    A stroke at x=0 is half a pixel outside the viewBox and renders as a
    clipped shape at some scales, which looks like a drawing mistake rather
    than like a bug.
    """
    viewbox = re.compile(r'viewBox="0 0 24 24"')
    for path in sorted(BADGES.glob("*.svg")):
        text = path.read_text(encoding="utf-8")
        assert text.startswith("<svg"), path.name
        assert viewbox.search(text), f"{path.name} is not on the 24x24 grid"
        assert 'stroke="currentColor"' in text, f"{path.name} is not themeable"
        assert 'fill="none"' in text, f"{path.name} should be stroke-only"
        assert "aria-hidden" in text, f"{path.name} is decorative and must say so"
        for value in re.findall(r'\b[xy](?:1|2)="(-?[\d.]+)"', text):
            assert -0.5 <= float(value) <= 24.5, f"{path.name} draws outside the box"
        for d in re.findall(r'\sd="([^"]+)"', text):
            for value in re.findall(r"-?\d+\.?\d*", d):
                assert abs(float(value)) <= 26, f"{path.name} has a runaway number"


def test_the_source_and_the_files_agree() -> None:
    """Regenerating from source reproduces exactly what is committed.

    The point of keeping the set as source is that a drawing can be reviewed as
    a diff. That only works if the files on disk are what the source says, and
    the cheapest way to be sure is to say it here.
    """
    for key, geometry in {**ICONS, **NOTE_ICONS}.items():
        assert source.render(geometry) == (BADGES / f"{key}.svg").read_text(
            encoding="utf-8"
        ), f"{key}.svg is stale; re-run `python -m tools.icons`"


def test_every_note_achievement_has_its_own_icon_too() -> None:
    """The note achievements used to all render `default.svg`.

    Thirty-eight identical squares underneath a hundred and twenty drawings, on
    the same page, in the same tiers. The two sets are checked against each other
    as well as within themselves, so a note icon can never be a registry icon
    either — a reader scanning the page should not have to work out which
    subsystem an entry came from.
    """
    keys = {a.key for a in note_achievements.load()}

    assert set(NOTE_ICONS) == keys, "note icons and note catalogue disagree"
    assert not (set(NOTE_ICONS) & set(ICONS)), (
        "a note achievement shares a drawing with a registry one"
    )


def test_no_icon_is_reused_between_the_two_catalogues() -> None:
    """No drawing appears twice, anywhere in the 158."""
    normalised = [re.sub(r"\s+", " ", g) for g in {**ICONS, **NOTE_ICONS}.values()]
    assert len(normalised) == len(set(normalised)), "two icons share a drawing"
