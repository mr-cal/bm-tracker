"""Timezone resolution.

Every "today" in this app is somebody's today, not the server's. The server is
UTC; a user in Auckland logging "today" is describing a day that has not started
in the server's frame at all. Getting this wrong shifts a whole history across
day boundaries, so the resolution lives in one place and is tested directly.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: The zone a person is assumed to be in when it cannot be worked out — an
#: account created without one, a stored value this Python has no tzdata for.
#:
#: Central, not UTC. A fallback is a guess about a human being, and a human
#: being is on Central time far more often than on the meridian — picking UTC
#: silently put everybody's day boundary six hours out and made "today" wrong
#: for the majority rather than for an edge case. `America/Chicago` is the IANA
#: name for it, and it carries its own daylight saving.
DEFAULT_TIMEZONE = "America/Chicago"

#: Used when a stored zone is not one this Python knows about. A missing tzdata
#: entry should not stop somebody logging a BM, and guessing where they are
#: beats refusing to serve them.
FALLBACK_TIMEZONE = DEFAULT_TIMEZONE

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


def local_now(timezone_name: str) -> datetime:
    """Return the current wall clock in the user's own timezone.

    Naive, because `occurred_local` is naive: a time is stored exactly as it was
    typed and never converted. So this is the value the log form has to
    pre-fill with, and returning UTC here put the server's clock in the box —
    a Central user's 8 pm entry was offered to them as 2 am.

    Args:
        timezone_name: An IANA timezone name.

    Returns:
        The current local time, with no zone attached.

    """
    zone = resolve_timezone(timezone_name)
    return (
        datetime.now(ZoneInfo(FALLBACK_TIMEZONE)).astimezone(zone).replace(tzinfo=None)
    )


def now_in(timezone_name: str) -> tuple[date, datetime]:
    """Return the user's local date and local time of day.

    Both halves are local, and they travel together: a caller cannot pair
    yesterday's date with this morning's clock. The date is what decides
    qualification and the time is what the log form offers, and both are
    answers about the user's day rather than the server's.

    Args:
        timezone_name: An IANA timezone name.

    Returns:
        A tuple of the user's local date and their local time of day.

    """
    now = local_now(timezone_name)
    return now.date(), now


def to_wall_clock(moment: datetime, timezone_name: str) -> datetime:
    """Return a stored naive-UTC instant as a wall clock in a timezone.

    The database convention is naive UTC and the display convention is
    the reader's own clock; this is the edge between the two. Rendering
    a stored instant without passing through here shows a reader a time
    as many hours off as their offset is — a feed card saying 6 pm for
    a noon log in a zone six hours behind the meridian.

    Args:
        moment: A naive UTC datetime, as stored.
        timezone_name: The IANA zone to express it in.

    Returns:
        A naive datetime: the wall clock in that zone.

    """
    return (
        moment.replace(tzinfo=ZoneInfo("UTC"))
        .astimezone(resolve_timezone(timezone_name))
        .replace(tzinfo=None)
    )


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
