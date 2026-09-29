"""Write the icon set and a contact sheet for it.

Usage:
    python -m tools.icons            # write the SVGs
    python -m tools.icons --sheet    # also write a contact sheet to /tmp
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.icons import sheet as sheet_module
from tools.icons import source
from tools.icons.icons import ICONS, NOTE_ICONS

BADGES = Path(__file__).resolve().parents[2] / "bm_tracker/static/img/badges"


def main() -> None:
    """Write every icon, and optionally a sheet to look at them in."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sheet", action="store_true", help="also write a contact sheet"
    )
    parser.add_argument(
        "--out", default="/tmp/icons.html", help="where the contact sheet goes"
    )
    args = parser.parse_args()

    written = source.write(BADGES, {**ICONS, **NOTE_ICONS})
    print(f"{len(written)} icons written to {BADGES}")
    if args.sheet:
        everything = {**ICONS, **NOTE_ICONS}
        path = sheet_module.sheet(sorted(everything), Path(args.out), note=len(ICONS))
        print(path)


if __name__ == "__main__":
    main()
