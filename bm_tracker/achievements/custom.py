"""Rules the declarative vocabulary cannot express.

The escape hatch, deliberately narrow: two of the twenty seed achievements need
arithmetic across several facts at once, and bending the vocabulary for them
would make it worse for the other eighteen. A rule here is a callable taking the
facts and returning `(unlocked, progress)`, exactly as a declarative one does.

The loader refuses to start if a rule here is never referenced by the registry,
so this file cannot quietly grow dead code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from bm_tracker.achievements.rules import Verdict

if TYPE_CHECKING:
    from collections.abc import Callable

    from bm_tracker.achievements.rules import Facts


#: Entries that must all be noted for Ghost Writer. Chosen to be a slog rather
#: than a weekend.
GHOST_WRITER_ENTRIES = 20

#: Consecutive spicy logged days for The Inferno.
FIERY_STREAK_DAYS = 5


def _every_entry_noted(facts: Facts) -> Verdict:
    """Reward writing down everything.

    A ratio is honest here. `noted_entry_count` is a running total for the year
    and the only thing standing between you and this is writing the next note,
    which is an ordinary thing to do.

    Args:
        facts: The facts to evaluate against.

    Returns:
        The `Verdict`.

    """
    if facts.get("bm_count_total") <= 0:
        return Verdict(unlocked=False, progress=None, current=None, target=None)
    noted = facts.get("noted_entry_count")
    return Verdict(
        noted >= GHOST_WRITER_ENTRIES,
        min(noted / GHOST_WRITER_ENTRIES, 1.0),
        noted,
        GHOST_WRITER_ENTRIES,
    )


def _fiery_streak(facts: Facts) -> Verdict:
    """Reward a run of consecutive logged days that were all spicy.

    No bar. This reads the *longest* spicy run ever, so a run of three is
    sixty per cent of nothing — the fourth day of a run has to be adjacent to
    the third, and last month's run cannot be extended from here. The count is
    worth showing; the percentage is not.

    Args:
        facts: The facts to evaluate against.

    Returns:
        The `Verdict`.

    """
    run = facts.get("max_spicy_consecutive_days")
    return Verdict(run >= FIERY_STREAK_DAYS, None, run, FIERY_STREAK_DAYS)


#: Custom rules, keyed by the name the registry refers to them by.
CUSTOM_RULES: Final[dict[str, Callable[[Facts], Verdict]]] = {
    "every_entry_noted": _every_entry_noted,
    "fiery_streak": _fiery_streak,
}
