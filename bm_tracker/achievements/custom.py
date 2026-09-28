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

if TYPE_CHECKING:
    from collections.abc import Callable

    from bm_tracker.achievements.rules import Facts


#: Entries that must all be noted for Ghost Writer. Chosen to be a slog rather
#: than a weekend.
GHOST_WRITER_ENTRIES = 20

#: Consecutive spicy logged days for The Inferno.
FIERY_STREAK_DAYS = 5


def _every_entry_noted(facts: Facts) -> tuple[bool, float]:
    """Reward writing down everything.

    Args:
        facts: The facts to evaluate against.

    Returns:
        `(unlocked, progress)`.

    """
    if facts.get("bm_count_total") <= 0:
        return False, 0.0
    noted = facts.get("noted_entry_count")
    return (noted >= GHOST_WRITER_ENTRIES, min(noted / GHOST_WRITER_ENTRIES, 1.0))


def _fiery_streak(facts: Facts) -> tuple[bool, float]:
    """Reward a run of consecutive logged days that were all spicy.

    Args:
        facts: The facts to evaluate against.

    Returns:
        `(unlocked, progress)`.

    """
    run = facts.get("max_spicy_consecutive_days")
    return (run >= FIERY_STREAK_DAYS, min(run / FIERY_STREAK_DAYS, 1.0))


#: Custom rules, keyed by the name the registry refers to them by.
CUSTOM_RULES: Final[dict[str, Callable[[Facts], tuple[bool, float]]]] = {
    "every_entry_noted": _every_entry_noted,
    "fiery_streak": _fiery_streak,
}
