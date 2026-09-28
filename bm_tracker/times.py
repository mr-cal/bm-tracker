"""One way to write a time of day.

A 24-hour clock is a machine convention. The people reading this are on a phone
in a bathroom at seven in the morning, and "7:30 am" is the thing they would
say out loud. So every rendered time goes through here rather than through a
`strftime` in a template, because `strftime` scattered across six templates is
six chances to render one page at 07:30 and the next at 19:30.

The one exception is the value of an `<input type="time">`, which has to be
24-hour because that is what the element expects; the browser displays it in
whatever format the reader's locale asks for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime

# Half a day, for the one place that has to know which half it is.
HOURS_PER_HALF_DAY = 12


def clock(moment: datetime | None) -> str:
    """Return a time of day the way a person would say it.

    Args:
        moment: The time to write, or None.

    Returns:
        Something like "7:30 am", or an empty string when there is no time.

    """
    if moment is None:
        return ""
    # %-I is not portable across platforms, so the hour is taken off the 12-hour
    # clock and turned back into a string.
    hour = moment.hour % HOURS_PER_HALF_DAY or HOURS_PER_HALF_DAY
    suffix = "am" if moment.hour < HOURS_PER_HALF_DAY else "pm"
    return f"{hour}:{moment.minute:02d} {suffix}"


def stamp(moment: datetime | None) -> str:
    """Return a date and a time of day, for a list row.

    Args:
        moment: The time to write, or None.

    Returns:
        Something like "26 Sep 7:30 am", or an empty string when there is none.

    """
    if moment is None:
        return ""
    return f"{moment.strftime('%-d %b')} {clock(moment)}"


def day_only(day: date | None) -> str:
    """Return a date without a time, for a group heading.

    Args:
        day: The date to write, or None.

    Returns:
        Something like "26 Sep", or an empty string when there is no date.

    """
    if day is None:
        return ""
    return day.strftime("%-d %b")
