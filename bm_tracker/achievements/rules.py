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

#: Facts that are a running total you can still move today, and that only ever
#: go up within the year.
#:
#: This set is the whole of the progress bar. Everything else is deliberately
#: excluded, because a percentage implies something the number cannot promise:
#: that the gap is a distance you are walking. For most facts it is not.
#:
#: `max_bms_in_day` at 9 of 10 is not ninety per cent of the way to anything —
#: the next one is not a tenth of a bowel movement, it is a completely different
#: day, and it will not arrive by carrying on as normal. `streak_longest` is a
#: record of something already past. `weekend_entry_count` runs on a rolling
#: seven-day window, so it can go *down*, which makes any percentage of it a
#: lie with a bar under it. The rest are flags, timestamps and sets.
#:
#: So those show a count — "9 / 10" — which is true, and the six below show a
#: bar, which is also true.
CUMULATIVE_FACTS: Final = frozenset(
    {
        "bm_count_total",
        "days_logged_total",
        "note_count",
        "noted_entry_count",
        "spicy_count",
        "streak_current",
    }
)

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
class Verdict:
    """What a rule says about a user, and what it is honest enough to show.

    Attributes:
        unlocked: Whether the rule is satisfied now.
        progress: 0.0-1.0, or `None` when a bar would be a lie. See
            `CUMULATIVE_FACTS`.
        current: The value measured, when it is a count worth stating.
        target: What it is measured against, or `None`.

    """

    unlocked: bool
    progress: float | None
    current: float | None
    target: float | None


#: The absence of a measurement, for rules that have nothing to measure.
NO_VERDICT: Final = Verdict(unlocked=False, progress=None, current=None, target=None)


@dataclass(frozen=True, slots=True)
class Rule:
    """One compiled achievement rule."""

    spec: dict[str, Any]

    def evaluate(self, facts: Facts) -> Verdict:
        """Return whether the rule is satisfied, and what may honestly be shown.

        Args:
            facts: The facts to evaluate against.

        Returns:
            A `Verdict`. `progress` is `None` unless the rule is built from
            cumulative totals, so a locked achievement shows a count rather than
            a percentage it has not earned.

        """
        return _eval(self.spec, facts)


def _eval(spec: Any, facts: Facts) -> Verdict:
    """Evaluate a rule specification.

    Args:
        spec: The rule tree.
        facts: The facts to evaluate against.

    Returns:
        The `Verdict` for the rule.

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


def _combine(children: Any, facts: Facts, *, require_all: bool) -> Verdict:
    """Evaluate an `all` or `any` group.

    Progress is the minimum for `all` and the maximum for `any`, which is what
    makes a partially-met requirement read as partial rather than as zero.

    The group only has a progress if *every* child does. One `all` containing a
    cumulative total and a calendar gate is a requirement you can be part-way
    through by logging, and gating; bar-filling the logged half would imply the
    gated half is coming, which it is not until its date.

    Args:
        children: The child rules.
        facts: The facts to evaluate against.
        require_all: Whether every child must be satisfied.

    Returns:
        The `Verdict` for the group.

    Raises:
        RuleError: If the group is empty or malformed.

    """
    if not isinstance(children, list) or not children:
        msg = "all/any must be a non-empty array of rules"
        raise RuleError(msg)

    results = [_eval(child, facts) for child in children]
    unlocked = (
        all(r.unlocked for r in results)
        if require_all
        else any(r.unlocked for r in results)
    )
    if any(r.progress is None for r in results):
        # The shortfall is not a distance, so say nothing about one. The count
        # of the closest child is still worth showing.
        best = min(results, key=_rank) if require_all else max(results, key=_rank)
        return Verdict(unlocked, None, best.current, best.target)
    best = (
        min(results, key=lambda r: r.progress)
        if require_all
        else max(results, key=lambda r: r.progress)
    )
    return Verdict(unlocked, best.progress, best.current, best.target)


def _rank(verdict: Verdict) -> tuple[float, float]:
    """Return a sort key for comparing two verdicts without a progress value."""
    return (verdict.current or 0.0) / (verdict.target or 1.0), verdict.current or 0.0


def _predicate(spec: dict[str, Any], facts: Facts) -> Verdict:
    """Evaluate a single `fact = comparison` predicate.

    Args:
        spec: One fact and its comparison.
        facts: The facts to evaluate against.

    Returns:
        The `Verdict` for the predicate.

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
        return Verdict(facts.get(name) == comparison, None, None, None)

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

    if op not in REACH_OPS:
        # "under 3 days" has no denominator, and the moment you pass it the
        # achievement is gone rather than complete. Nothing to show.
        return Verdict(_NUMERIC[op](value, float(target)), None, None, None)

    target_value = float(target)
    met = _NUMERIC[op](value, target_value)
    if name not in CUMULATIVE_FACTS:
        return Verdict(met, None, value, target_value)
    return Verdict(met, _progress(value, target_value), value, target_value)


#: Comparisons that mean "get to at least this much", and so have a denominator
#: a percentage can honestly divide by.
REACH_OPS: Final = frozenset({"gte", "gt"})

_NUMERIC = {
    "gte": lambda v, t: v >= t,
    "gt": lambda v, t: v > t,
    "lte": lambda v, t: v <= t,
    "lt": lambda v, t: v < t,
    "eq": lambda v, t: v == t,
}


def _compare_special(name: str, value: float, op: str, target: Any) -> Verdict:
    """Evaluate a comparison that is not a plain numeric one.

    Args:
        name: The fact being compared.
        value: Its current value.
        op: The comparison operator.
        target: The comparison's operand.

    Returns:
        The `Verdict` for the comparison.

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
        return Verdict(met, None, None, None)

    # A window, not a distance: there is no "40 per cent of the way to between
    # 23:00 and 05:00", and the value is a clock reading rather than a count.
    return Verdict(float(low) <= value <= float(high), None, None, None)


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
