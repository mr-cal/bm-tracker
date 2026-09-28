"""Loading and validating the achievement registry.

The registry is `achievements.toml`. It is read once at startup and validated
there, so a malformed definition fails the deploy rather than producing an
achievement that quietly never unlocks.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from bm_tracker.achievements import rules
from bm_tracker.achievements.custom import CUSTOM_RULES

REGISTRY_PATH: Final = Path(__file__).parent / "achievements.toml"

DEFAULT_ICON: Final = "default"
BADGE_DIR: Final = Path(__file__).parent.parent / "static" / "img" / "badges"

REQUIRED_KEYS: Final = frozenset({"key", "name", "description", "tier", "rule"})


class RegistryError(ValueError):
    """Raised when the registry is malformed."""


@dataclass(frozen=True, slots=True)
class Achievement:
    """One definition, compiled and validated."""

    key: str
    name: str
    description: str
    tier: str
    icon: str
    points: int
    rule: rules.Rule | None
    custom: str | None

    def evaluate(self, facts: rules.Facts) -> tuple[bool, float]:
        """Return whether it is unlocked, and how close it is.

        Args:
            facts: The facts to evaluate against.

        Returns:
            `(unlocked, progress)`.

        """
        if self.custom is not None:
            return CUSTOM_RULES[self.custom](facts)
        assert self.rule is not None  # noqa: S101 - guaranteed by the loader
        return self.rule.evaluate(facts)


@dataclass(frozen=True, slots=True)
class Registry:
    """Every achievement, keyed and ordered."""

    achievements: tuple[Achievement, ...]
    tiers: dict[str, int]
    # Lifetime points before each tier's names become visible. A tier missing
    # from this is visible from the start, so a new tier cannot accidentally
    # hide itself.
    reveal_at: dict[str, int]

    def __len__(self) -> int:
        """Return how many achievements are defined."""
        return len(self.achievements)

    def points_to_reveal(self, tier: str) -> int:
        """Return the points needed before a tier's names are visible.

        Args:
            tier: The tier name.

        Returns:
            The threshold, or 0 for a tier that is never hidden.

        """
        return self.reveal_at.get(tier, 0)

    def get(self, key: str) -> Achievement:
        """Return an achievement by key.

        Args:
            key: The achievement key.

        Returns:
            The `Achievement`.

        Raises:
            RegistryError: If the key is not defined.

        """
        for achievement in self.achievements:
            if achievement.key == key:
                return achievement
        msg = f"Unknown achievement {key!r}"
        raise RegistryError(msg)


def load(path: Path | None = None) -> Registry:
    """Read and validate the registry.

    Args:
        path: An alternative registry file, for tests.

    Returns:
        The validated `Registry`.

    Raises:
        RegistryError: If anything is malformed.

    """
    source = path or REGISTRY_PATH
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        msg = f"Registry not found: {source}"
        raise RegistryError(msg) from exc
    except tomllib.TOMLDecodeError as exc:
        msg = f"Registry is not valid TOML: {exc}"
        raise RegistryError(msg) from exc

    tiers = _tiers(data)
    entries = data.get("achievement", [])
    if not isinstance(entries, list) or not entries:
        msg = "Registry defines no achievements"
        raise RegistryError(msg)

    seen: set[str] = set()
    compiled: list[Achievement] = []
    for index, entry in enumerate(entries):
        compiled.append(_compile(entry, tiers, seen, index))

    for name in CUSTOM_RULES:
        if not any(a.custom == name for a in compiled):
            msg = f"Custom rule {name!r} is defined but never used"
            raise RegistryError(msg)

    return Registry(
        achievements=tuple(compiled), tiers=tiers, reveal_at=_reveal_at(data, tiers)
    )


def _reveal_at(data: dict[str, Any], tiers: dict[str, int]) -> dict[str, int]:
    """Validate the tier-to-reveal-points table.

    Args:
        data: The parsed registry.
        tiers: The known tier names, so a typo cannot silently hide a tier
            forever.

    Returns:
        A mapping of tier name to the points needed to see it.

    Raises:
        RegistryError: If the table names a tier that does not exist.

    """
    raw = data.get("tier_reveal", {})
    if not isinstance(raw, dict):
        msg = "[tier_reveal] must be a table of tier to points"
        raise RegistryError(msg)
    reveal: dict[str, int] = {}
    for name, points in raw.items():
        if str(name) not in tiers:
            msg = f"[tier_reveal] names unknown tier {name!r}"
            raise RegistryError(msg)
        if not isinstance(points, int) or points < 0:
            msg = f"Tier {name!r} must have a non-negative integer reveal value"
            raise RegistryError(msg)
        reveal[str(name)] = points
    return reveal


def _tiers(data: dict[str, Any]) -> dict[str, int]:
    """Validate the tier-to-points table.

    Args:
        data: The parsed registry.

    Returns:
        A mapping of tier name to points.

    Raises:
        RegistryError: If the table is missing or malformed.

    """
    raw = data.get("achievement_tiers")
    if not isinstance(raw, dict) or not raw:
        msg = "Registry must define [achievement_tiers]"
        raise RegistryError(msg)
    tiers: dict[str, int] = {}
    for name, points in raw.items():
        if not isinstance(points, int) or points < 0:
            msg = f"Tier {name!r} must have a non-negative integer point value"
            raise RegistryError(msg)
        tiers[str(name)] = points
    return tiers


def _compile(
    entry: Any, tiers: dict[str, int], seen: set[str], index: int
) -> Achievement:
    """Validate and compile one definition.

    Args:
        entry: The raw table from the registry.
        tiers: The tier-to-points table.
        seen: Keys already compiled, mutated to add this one.
        index: The definition's position, for error messages.

    Returns:
        The compiled `Achievement`.

    Raises:
        RegistryError: If the definition is malformed.

    """
    where = f"achievement #{index + 1}"
    if not isinstance(entry, dict):
        msg = f"{where} is not a table"
        raise RegistryError(msg)

    missing = REQUIRED_KEYS - set(entry)
    if missing:
        msg = f"{where} is missing {sorted(missing)}"
        raise RegistryError(msg)

    key = str(entry["key"])
    if key in seen:
        msg = f"Duplicate achievement key {key!r}"
        raise RegistryError(msg)
    seen.add(key)

    tier = str(entry["tier"])
    if tier not in tiers:
        msg = f"{key!r} uses tier {tier!r}, which has no point value"
        raise RegistryError(msg)

    icon = str(entry.get("icon", DEFAULT_ICON))
    if icon != DEFAULT_ICON and not (BADGE_DIR / f"{icon}.svg").is_file():
        # A typo'd icon fails the deploy rather than rendering a broken image.
        msg = f"{key!r} names icon {icon!r}, which does not exist in {BADGE_DIR.name}/"
        raise RegistryError(msg)

    spec = entry["rule"]
    custom = (
        str(spec["custom"]) if isinstance(spec, dict) and "custom" in spec else None
    )
    if custom is not None and custom not in CUSTOM_RULES:
        msg = f"{key!r} uses unknown custom rule {custom!r}"
        raise RegistryError(msg)
    if custom is None and not isinstance(spec, dict):
        msg = f"{key!r} has a malformed rule"
        raise RegistryError(msg)

    try:
        compiled = None if custom else rules.Rule(spec=spec)
        if compiled is not None:
            _validate_spec(spec, key)
    except rules.RuleError as exc:
        msg = f"{key!r}: {exc}"
        raise RegistryError(msg) from exc

    return Achievement(
        key=key,
        name=str(entry["name"]),
        description=str(entry["description"]),
        tier=tier,
        icon=icon,
        points=tiers[tier],
        rule=compiled,
        custom=custom,
    )


def _validate_spec(spec: Any, key: str) -> None:
    """Walk a rule tree, checking every fact name it references.

    Args:
        spec: The rule tree.
        key: The achievement key, for error messages.

    Raises:
        RegistryError: If an unknown fact or comparison is referenced.

    """
    if not isinstance(spec, dict):
        msg = f"{key!r} has a malformed rule"
        raise RegistryError(msg)

    for combinator in ("all", "any"):
        if combinator in spec:
            children = spec[combinator]
            if not isinstance(children, list) or not children:
                msg = f"{key!r}: {combinator} must be a non-empty array"
                raise RegistryError(msg)
            for child in children:
                _validate_spec(child, key)
            return

    if "custom" in spec:
        return

    if len(spec) != 1:
        msg = f"{key!r}: a predicate must name exactly one fact, got {sorted(spec)}"
        raise RegistryError(msg)
    ((name, comparison),) = spec.items()
    if name not in rules.KNOWN_FACTS:
        msg = f"{key!r}: unknown fact {name!r}"
        raise RegistryError(msg)
    if isinstance(comparison, dict):
        ((op, _),) = comparison.items()
        if op not in rules.NUMERIC_OPS and op not in rules.SPECIAL_OPS:
            msg = f"{key!r}: unknown comparison {op!r} for {name!r}"
            raise RegistryError(msg)


__all__ = ["Achievement", "Registry", "RegistryError", "load"]
