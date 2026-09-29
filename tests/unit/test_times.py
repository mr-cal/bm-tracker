"""Tests for the time format.

Every rendered time goes through `bm_tracker.times`, because a `strftime`
scattered across six templates is six chances to render one page at 07:30 and
the next at 7:30 am.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from bm_tracker import times
from bm_tracker.times import feed_when


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (0, 5, "12:05 am"),
        (7, 30, "7:30 am"),
        (11, 59, "11:59 am"),
        (12, 0, "12:00 pm"),
        (13, 45, "1:45 pm"),
        (23, 59, "11:59 pm"),
    ],
)
def test_a_time_reads_the_way_a_person_says_it(
    hour: int, minute: int, expected: str
) -> None:
    assert times.clock(datetime(2026, 9, 26, hour, minute)) == expected


def test_minutes_are_always_two_digits() -> None:
    """9:05, not 9:5 — a clock that drops the zero looks like a typo."""
    assert times.clock(datetime(2026, 9, 26, 21, 5)) == "9:05 pm"


def test_stamp_puts_the_date_before_the_time() -> None:
    assert times.stamp(datetime(2026, 9, 6, 19, 30)) == "6 Sep 7:30 pm"


def test_nothing_renders_as_nothing() -> None:
    """A missing time is an empty string, not the word None."""
    assert times.clock(None) == ""
    assert times.stamp(None) == ""
    assert times.day_only(None) == ""


def test_day_only_has_no_clock_on_it() -> None:
    assert times.day_only(date(2026, 9, 6)) == "6 Sep"


@pytest.mark.parametrize(
    ("days_ago", "expected"),
    [
        (0, "30 Jun"),
        (1, "29 Jun"),
        (90, "1 Apr"),
        (91, "31 Mar 2026"),
        (400, "26 May 2025"),
    ],
)
def test_the_year_is_only_shown_once_it_is_doing_work(
    days_ago: int, expected: str
) -> None:
    """The common case is this week, and the year is noise on it.

    Args:
        days_ago: How far back the entry is.
        expected: What the feed should render.

    """
    today = date(2026, 6, 30)
    moment = datetime(2026, 6, 30) - timedelta(days=days_ago)

    assert feed_when(moment, today) == expected
