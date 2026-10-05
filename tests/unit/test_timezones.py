"""Tests for timezone resolution.

Every "now" in this app is somebody's now. `local_now` is the value the log
form pre-fills with, and a time is stored exactly as it was typed and never
converted afterwards — so a UTC clock handed to a user six hours from here is
not a formatting problem, it is a wrong entry saved correctly.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bm_tracker.timezones import local_now, now_in

#: UTC+14 with no daylight saving, so the offset from UTC is the same number
#: whatever day or hour the suite happens to run on.
FAR_ZONE = "Pacific/Kiritimati"


def test_now_in_returns_the_users_own_wall_clock() -> None:
    """The clock offered to a user is their clock, not the server's."""
    moment = local_now(FAR_ZONE)
    utc = datetime.now(ZoneInfo("UTC")).replace(tzinfo=None)

    assert moment.tzinfo is None, "a stored wall-clock time carries no zone"
    # A minute either side, because the two clocks were read a moment apart.
    assert (
        timedelta(hours=13, minutes=59)
        <= moment - utc
        <= timedelta(hours=14, minutes=1)
    )


def test_both_halves_of_now_in_are_local() -> None:
    """The date and the time have to be the same user's, or they disagree.

    Pairing yesterday's date with today's clock puts an entry on the wrong day,
    which is a different bug from the wrong time and is fixed in the same place.
    """
    day, moment = now_in(FAR_ZONE)

    assert day == moment.date()
    assert abs(moment - local_now(FAR_ZONE)) < timedelta(seconds=5)
