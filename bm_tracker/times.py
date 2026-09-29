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


#: How far back an entry can be before its date needs the year on it. Three
#: months is about as long as anyone holds a date in their head without it, and
#: it happens to be a quarter, so "last quarter" and "this year" line up with
#: the way people already talk about their own year.
DAYS_BEFORE_YEAR_MATTERS = 90


def feed_when(moment: datetime, today: date) -> str:
    """Return a feed date, with the year only when it is doing any work.

    The year used to be on every card, which made the common case — scrolling
    this week — read as though everything were old. It is not noise on an entry
    from last March and it is noise on one from this morning, so it is shown
    only where the year is what you cannot infer, and dropped everywhere else.

    Args:
        moment: When the thing happened.
        today: The reader's today, in their own timezone.

    Returns:
        "21 Jan" for anything inside the window, "21 Jan 2025" beyond it.

    """
    if (today - moment.date()).days > DAYS_BEFORE_YEAR_MATTERS:
        return moment.strftime("%-d %b %Y")
    return moment.strftime("%-d %b")
