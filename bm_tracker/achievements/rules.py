"""The achievement rule vocabulary and its evaluator.

Small on purpose. A registry heading for 300 entries is mostly combinations of
a dozen facts, and a tiny declarative vocabulary covers those directly. Rules
that genuinely need logic go through `custom.py` under the same key.

Every definition is validated at import, not at request time. A typo'd fact name
is a typo'd fact name whether it is found in development or in production, and
finding it at startup means it fails the deploy rather than producing an
achievement that silently never unlocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Protocol


class Facts(Protocol):
    """The read-only view of a user's derived facts that rules may use."""

    def get(self, key: str) -> float:  # pragma: no cover - protocol
        """Return a fact's value, or zero when it does not exist.

        Args:
            key: The fact name.

        Returns:
            The value.

        """
        ...


#: Numeric comparisons a rule may use.
NUMERIC_OPS: Final = frozenset({"gte", "gt", "lte", "lt", "eq"})

#: Comparisons that need more than a number.
SPECIAL_OPS: Final = frozenset({"between"})

#: Every fact a rule may reference. Validated at import, so an achievement using
#: a fact nothing computes is a startup error rather than a silent never.
KNOWN_FACTS: Final[frozenset[str]] = frozenset(
    {
        "bm_count_total",
        "bm_count_day",
        "max_bms_in_day",
        "days_logged_total",
        "note_count",
        "spicy_count",
        "bristol_type",
        "bristol_types_seen",
        "streak_current",
        "streak_longest",
        "time_of_day",
        "fastest_entry_delay",
        "logged_same_day",
        "gap_since_previous_days",
        "noted_entry_count",
        "max_spicy_consecutive_days",
        # Calendar. One fact per occasion rather than a month/day pair, so a rule
        # reads "logged on the Ides of March" instead of two comparisons that
        # only hold while they are being evaluated — and so a history that
        # already contains the date can still earn it.
        "logged_jan_1",
        "logged_feb_2",
        "logged_feb_14",
        "logged_feb_29",
        "logged_mar_15",
        "logged_apr_1",
        "logged_may_1",
        "logged_jun_21",
        "logged_oct_31",
        "logged_nov_5",
        "logged_dec_21",
        "logged_dec_24",
        "logged_dec_25",
        "logged_dec_26",
        "logged_dec_31",
        "logged_friday_13",
        "distinct_weekdays_logged",
        "distinct_months_logged",
        "weekend_entry_count",
        # Self-denial. The anti-achievements, which is where the app is funniest:
        # a note you did not write, a day filled in after the fact, an entry that
        # did not survive.
        "longest_run_without_note",
        "all_entries_noted",
        "backfilled_days",
        "deleted_entries",
    }
)


class RuleError(ValueError):
    """Raised when a definition is malformed."""


@dataclass(frozen=True, slots=True)
class Rule:
    """One compiled achievement rule."""

    spec: dict[str, Any]

    def evaluate(self, facts: Facts) -> tuple[bool, float]:
        """Return whether the rule is satisfied, and how close it is.

        Args:
            facts: The facts to evaluate against.

        Returns:
            `(unlocked, progress)` where progress is 0.0-1.0, so a locked
            achievement can still show "14 / 20".

        """
        return _eval(self.spec, facts)


def _eval(spec: Any, facts: Facts) -> tuple[bool, float]:
    """Evaluate a rule specification.

    Args:
        spec: The rule tree.
        facts: The facts to evaluate against.

    Returns:
        `(unlocked, progress)`.

    Raises:
        RuleError: If the specification is malformed.

    """
    if not isinstance(spec, dict):
        msg = f"Rule must be a table, got {type(spec).__name__}"
        raise RuleError(msg)

    if "all" in spec:
        return _combine(spec["all"], facts, require_all=True)
    if "any" in spec:
        return _combine(spec["any"], facts, require_all=False)
    if "custom" in spec:
        msg = "A custom rule must be resolved before evaluation"
        raise RuleError(msg)
    return _predicate(spec, facts)


def _combine(children: Any, facts: Facts, *, require_all: bool) -> tuple[bool, float]:
    """Evaluate an `all` or `any` group.

    Progress is the minimum for `all` and the maximum for `any`, which is what
    makes a partially-met requirement read as partial rather than as zero.

    Args:
        children: The child rules.
        facts: The facts to evaluate against.
        require_all: Whether every child must be satisfied.

    Returns:
        `(unlocked, progress)`.

    Raises:
        RuleError: If the group is empty or malformed.

    """
    if not isinstance(children, list) or not children:
        msg = "all/any must be a non-empty array of rules"
        raise RuleError(msg)

    results = [_eval(child, facts) for child in children]
    if require_all:
        return all(ok for ok, _ in results), min(p for _, p in results)
    return any(ok for ok, _ in results), max(p for _, p in results)


def _predicate(spec: dict[str, Any], facts: Facts) -> tuple[bool, float]:
    """Evaluate a single `fact = comparison` predicate.

    Args:
        spec: One fact and its comparison.
        facts: The facts to evaluate against.

    Returns:
        `(unlocked, progress)`.

    Raises:
        RuleError: If the fact or comparison is not recognised.

    """
    if len(spec) != 1:
        msg = f"A predicate must name exactly one fact, got {sorted(spec)}"
        raise RuleError(msg)

    ((name, comparison),) = spec.items()
    if name not in KNOWN_FACTS:
        msg = f"Unknown fact {name!r}. Known: {sorted(KNOWN_FACTS)}"
        raise RuleError(msg)

    # A bare value is equality, which reads well for booleans and small counts.
    if not isinstance(comparison, dict):
        return (
            facts.get(name) == comparison,
            1.0 if facts.get(name) == comparison else 0.0,
        )

    if len(comparison) != 1:
        msg = f"{name} must have exactly one comparison"
        raise RuleError(msg)

    ((op, target),) = comparison.items()
    value = facts.get(name)

    if op in SPECIAL_OPS:
        return _compare_special(name, value, op, target)

    if op not in NUMERIC_OPS:
        msg = f"Unknown comparison {op!r} for {name!r}"
        raise RuleError(msg)

    met = _NUMERIC[op](value, float(target))
    return met, _progress(value, float(target))


_NUMERIC = {
    "gte": lambda v, t: v >= t,
    "gt": lambda v, t: v > t,
    "lte": lambda v, t: v <= t,
    "lt": lambda v, t: v < t,
    "eq": lambda v, t: v == t,
}


def _compare_special(
    name: str, value: float, op: str, target: Any
) -> tuple[bool, float]:
    """Evaluate a comparison that is not a plain numeric one.

    Args:
        name: The fact being compared.
        value: Its current value.
        op: The comparison operator.
        target: The comparison's operand.

    Returns:
        `(unlocked, progress)`.

    Raises:
        RuleError: If the operand is malformed.

    """
    if op != "between":
        msg = f"Unknown comparison {op!r} for {name!r}"
        raise RuleError(msg)

    if not isinstance(target, list) or len(target) != 2:  # noqa: PLR2004
        msg = f"{name} between needs [low, high]"
        raise RuleError(msg)

    low, high = str(target[0]), str(target[1])

    if name == "time_of_day":
        # A window that wraps midnight, like 23:00-05:00, has `low > high`.
        # Fact is expressed as the hour of day plus a minute fraction.
        stamp = f"{int(value) % 24:02d}:{(value % 1) * 60:02.0f}"
        met = (low <= stamp <= high) if low <= high else (stamp >= low or stamp <= high)
        return met, 1.0 if met else 0.0

    met = float(low) <= value <= float(high)
    return met, _progress(value, float(high))


def _progress(value: float, target: float) -> float:
    """Return how far a value is towards a target, clamped to 0.0-1.0.

    Args:
        value: The current value.
        target: The target value.

    Returns:
        Progress between 0.0 and 1.0.

    """
    if target <= 0:
        return 1.0 if value >= target else 0.0
    return max(0.0, min(1.0, value / target))


__all__ = [
    "KNOWN_FACTS",
    "NUMERIC_OPS",
    "SPECIAL_OPS",
    "Facts",
    "Rule",
    "RuleError",
]
