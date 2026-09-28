"""Timezone resolution.

Every "today" in this app is somebody's today, not the server's. The server is
UTC; a user in Auckland logging "today" is describing a day that has not started
in the server's frame at all. Getting this wrong shifts a whole history across
day boundaries, so the resolution lives in one place and is tested directly.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Fallback when a stored timezone is not a zone this Python knows about. A
# missing tzdata entry should not stop somebody logging a BM.
FALLBACK_TIMEZONE = "UTC"

MAX_HOUR = 23
MAX_MINUTE = 59
# HH:MM, or HH:MM:SS if a seconds component is included.
TIME_PART_COUNTS = (2, 3)


def resolve_timezone(name: str) -> ZoneInfo:
    """Return the zone for an IANA name, falling back to UTC.

    Args:
        name: An IANA timezone name, e.g. "Europe/London".

    Returns:
        The `ZoneInfo`, or UTC when the name is unusable.

    """
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo(FALLBACK_TIMEZONE)


def is_valid_timezone(name: str) -> bool:
    """Return whether a string names a timezone this Python can resolve.

    Args:
        name: The candidate name.

    Returns:
        Whether it resolves.

    """
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False
    return True


def today_for(timezone_name: str, *, now: datetime | None = None) -> date:
    """Return the current date in a user's own timezone.

    Args:
        timezone_name: An IANA timezone name.
        now: The instant to resolve, for testing. Defaults to the real now.

    Returns:
        The date it is for that user.

    """
    moment = now or datetime.now(ZoneInfo(FALLBACK_TIMEZONE))
    return moment.astimezone(resolve_timezone(timezone_name)).date()


def now_in(timezone_name: str) -> tuple[date, datetime]:
    """Return the current naive UTC instant alongside the user's local date.

    The local date is what decides qualification, so the two travel together
    and a caller cannot accidentally use the server's date.

    Args:
        timezone_name: An IANA timezone name.

    Returns:
        A tuple of the user's local date and the current instant.

    """
    zone = resolve_timezone(timezone_name)
    now = datetime.now(ZoneInfo(FALLBACK_TIMEZONE))
    return now.astimezone(zone).date(), now


def year_bounds(year: int) -> tuple[date, date]:
    """Return the first and last day of a calendar year, inclusive.

    Args:
        year: The year.

    Returns:
        The year's first and last date.

    """
    return date(year, 1, 1), date(year, 12, 31)


def parse_date(value: str) -> date | None:
    """Parse an ISO date, returning `None` rather than raising.

    Args:
        value: The candidate date, e.g. "2026-01-09".

    Returns:
        The parsed date, or `None` if it is not a valid ISO date.

    """
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def parse_time(value: str) -> str | None:
    """Validate an `HH:MM` time, returning it normalised or `None`.

    Args:
        value: The candidate time.

    Returns:
        The time as `HH:MM`, or `None` if it is not a valid 24-hour time.

    """
    if not value:
        return None
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= MAX_HOUR and 0 <= minute <= MAX_MINUTE):
        return None
    return f"{hour:02d}:{minute:02d}"
