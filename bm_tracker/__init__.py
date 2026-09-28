"""bm-tracker: a private daily bowel-movement tracker with streaks and points."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bm-tracker")
except PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
