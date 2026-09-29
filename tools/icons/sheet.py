"""Render a contact sheet of the icon set, for looking at.

Every icon in the set on one grid, at the size the collection page actually
uses. This exists because the previous set passed every check that does not
involve looking: 43 files, a loader that verified each name resolved, tests that
counted them, and two pairs of byte-identical SVGs named after different
achievements. Reading the directory listing cannot see that. A grid can, in one
glance, which is the entire reason this file exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

BADGES = Path(__file__).resolve().parents[2] / "bm_tracker/static/img/badges"


def sheet(
    names: list[str], out: Path, *, size: int = 44, columns: int = 8, note: int = 0
) -> Path:
    """Write an HTML contact sheet for the named icons.

    Args:
        names: The icon stems to include, in the order to show them.
        out: Where to write the HTML.
        size: The rendered icon size in CSS pixels.
        columns: How many per row.
        note: How many leading names are registry icons, so the note set can be
            marked as its own block. A wall of one hundred and fifty-eight
            drawings is a lot to scan without a line between the two halves.

    Returns:
        The path written.

    """
    cells = []
    for i, name in enumerate(names):
        svg = (BADGES / f"{name}.svg").read_text(encoding="utf-8")
        svg = svg.replace('width="24"', f'width="{size}"').replace(
            'height="24"', f'height="{size}"'
        )
        cls = "c note" if i >= note else "c"
        cells.append(f'<div class="{cls}">{svg}<small>{name}</small></div>')

    html = f"""<!doctype html><meta charset="utf-8">
<style>
body{{background:#141414;color:#eee;font:12px system-ui;margin:0;padding:14px}}
.g{{display:grid;grid-template-columns:repeat({columns},1fr);gap:8px}}
.c{{background:#202020;border:1px solid #383838;border-radius:8px;padding:6px;text-align:center}}
svg{{width:{size}px;height:{size}px;display:block;margin:0 auto 3px}}
small{{color:#999;font-size:9px}}
.c.note{{border-color:#2f4a6b;background:#1a2230}}
</style>
<div class="g">{''.join(cells)}</div>
"""
    out.write_text(html, encoding="utf-8")
    return out


def main() -> None:
    """Write a sheet of every icon in the badges directory."""
    names = sorted(p.stem for p in BADGES.glob("*.svg"))
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/sheet.html")
    print(sheet(names, out), len(names), "icons")


if __name__ == "__main__":
    main()
