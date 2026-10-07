"""What a viewer is allowed to see of another person's data.

Every cross-user read goes through this module. It is the only place that knows
the rules, which is the point: a template or a query that decides visibility for
itself is a leak waiting to happen.

The rule is per *surface*, not per user. Other users see a person's shape and
their comedy — streaks, points, achievements, and the notes they chose to write.
They do not see the detail: not the time a BM happened, not its Bristol type as
an individual event, not strain or flags, and not which days were backfilled.

The year is a viewing convention and is applied by the callers, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime

    from bm_tracker.models import BmEntry, DailyLog, User


@dataclass(frozen=True, slots=True)
class VisibleDay:
    """A day as another user is allowed to see it.

    The date and the counts are public because they are the activity signal the
    group actually wants. Everything finer is absent, not merely hidden.
    """

    day: date
    n_bms: int
    note: str | None
    note_is_superseded: bool
    qualified: bool


@dataclass(frozen=True, slots=True)
class VisibleProfile:
    """Another participant, as the viewer may see them.

    Note what is *not* here: no Bristol distribution, no spicy rate, no counts by
    hour, no entry times, and no indication of which days were backfilled.
    """

    user: User
    streak: int
    longest_streak: int
    points: int
    days_logged: int
    note_count: int
    days: tuple[VisibleDay, ...]
    achievements: tuple[str, ...]

    @property
    def display_name(self) -> str:
        """Return the name to show for this person."""
        return self.user.display_name


def is_own_data(viewer: User, subject: User) -> bool:
    """Return whether a viewer is looking at their own data.

    Args:
        viewer: The signed-in user.
        subject: Whose data is being read.

    Returns:
        Whether they are the same person.

    """
    return viewer.id == subject.id


def can_see_detail(viewer: User, subject: User) -> bool:
    """Return whether a viewer may see a person's fine-grained detail.

    Admins can, because they administer the accounts and the year-end analysis
    reads from the database rather than the browser.

    Args:
        viewer: The signed-in user.
        subject: Whose data is being read.

    Returns:
        Whether the detail is available.

    """
    return viewer.is_admin or is_own_data(viewer, subject)


def day_for_others(day: DailyLog, *, qualified: bool) -> VisibleDay:
    """Project a day down to what another user may see.

    Args:
        day: The real row.
        qualified: Whether it was recorded on the day it happened.

    Returns:
        The visible projection.

    """
    return VisibleDay(
        day=day.day,
        n_bms=day.n_bms,
        note=day.notes if day.is_note_live else None,
        note_is_superseded=day.is_superseded,
        # Backfilled days are marked, but the *fact* of which days were late is
        # not published: it is the kind of detail that turns a friendly log into
        # a surveillance surface, and it is not needed for any of the three
        # things other users are allowed to see.
        qualified=qualified,
    )


def entry_for_self(entry: BmEntry, occurred: datetime) -> dict[str, object]:
    """Project an entry for its owner, in full.

    Args:
        entry: The real row.
        occurred: The wall-clock time it happened.

    Returns:
        The fields to render.

    """
    return {
        "id": entry.id,
        "occurred_local": occurred,
        "bristol_type": entry.bristol_type,
        "spicy": bool(entry.spicy),
        "notes": entry.notes,
        "has_note": entry.has_note,
    }


#: The fields a cross-user payload may contain. A feed item that grows a key
#: outside this set is a leak; the test asserts the shape rather than trusting
#: each call site to remember.
PUBLIC_ITEM_KEYS = frozenset(
    {
        "kind",
        "at",
        "user",
        "display_name",
        "text",
        "achievements",
        "points",
        "year",
    }
)


def assert_public(item: dict[str, object]) -> None:
    """Raise if a feed item carries anything a viewer must not see.

    Args:
        item: The rendered feed item.

    Raises:
        ValueError: If the item contains a private key.

    """
    extra = set(item) - PUBLIC_ITEM_KEYS
    if extra:
        msg = f"Feed item leaked non-public keys: {sorted(extra)}"
        raise ValueError(msg)
