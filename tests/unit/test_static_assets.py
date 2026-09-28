"""Tests for the vendored static assets.

A vendored file that references something that was not vendored with it is a
404 on every page load, forever, and it is easy to reintroduce: the fix is
usually "re-download the upstream file", which brings the reference back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent.parent / "bm_tracker" / "static"
# `/*# sourceMappingURL=name */` and the `//# sourceMappingURL=` form.
SOURCE_MAP = re.compile(r"sourceMappingURL=([^\s*]+)")


def _assets() -> list[Path]:
    """Return every CSS and JavaScript file served to a browser."""
    return [
        path
        for path in STATIC.rglob("*")
        if path.is_file() and path.suffix in {".css", ".js"}
    ]


def test_there_are_assets_to_check() -> None:
    """Guard the guard: a glob that matched nothing would pass silently."""
    assert len(_assets()) > 5


@pytest.mark.parametrize("asset", _assets(), ids=lambda p: p.name)
def test_no_asset_references_a_source_map_that_is_not_there(asset: Path) -> None:
    """Every source map an asset names must exist beside it.

    Bootstrap's minified CSS shipped with a `sourceMappingURL` and the map was
    not vendored, so the browser asked for a file that was never there and
    logged a 404 on every single page load.
    """
    referenced = SOURCE_MAP.findall(asset.read_text())

    for name in referenced:
        assert (asset.parent / name).is_file(), (
            f"{asset.name} references a source map that is not present: {name}"
        )
