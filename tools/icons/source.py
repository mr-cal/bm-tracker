"""The achievement icon set, as source.

Each entry is the geometry inside a 24x24 box. The wrapper — the `svg` element,
the `currentColor` stroke, the round caps — is applied by `render()` rather
than written 120 times, because the wrapper is the part that has to be
identical across the set and the geometry is the part that has to be different.

House style, and the reason for every attribute in it:

24x24, because that is the grid these are drawn on and the only size at which
the whole set is legible. `fill="none"` and `stroke="currentColor"`, so an icon
inherits the text colour of whatever it sits in and needs no second copy for
dark mode. `stroke-width="1.7"`, a shade over Lucide's 2 — thinner reads as
considered at 40px and survives being scaled down into a 24px tile without
filling in. Round caps and joins, so a stroke that ends still looks deliberate
at this size, which square ends do not.

The keys are achievement keys. One icon per achievement, deliberately: sharing
an icon is how the previous set ended up with five flames and two pairs of
byte-identical files, and a collection is a thing you look at, so two entries
that look the same are two entries you cannot tell apart.
"""

from __future__ import annotations

from pathlib import Path

STROKE_WIDTH = 1.7

#: The geometry for every achievement, keyed by achievement key.
ICONS: dict[str, str] = {}


def render(geometry: str) -> str:
    """Return a complete standalone SVG for one icon.

    Args:
        geometry: The shapes inside the viewBox.

    Returns:
        A complete SVG document.

    """
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        f' stroke="currentColor" stroke-width="{STROKE_WIDTH}"'
        ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"'
        f' focusable="false">\n  {geometry.strip()}\n</svg>\n'
    )


def write(target: Path, icons: dict[str, str] | None = None) -> list[Path]:
    """Write every icon to the badges directory.

    Args:
        target: The directory to write into.
        icons: The icon source, defaulting to `ICONS`.

    Returns:
        The files written, in key order.

    """
    source = ICONS if icons is None else icons
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for key in sorted(source):
        path = target / f"{key}.svg"
        path.write_text(render(source[key]), encoding="utf-8")
        written.append(path)
    return written
