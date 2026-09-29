"""Achievements that can only be found by reading what somebody wrote.

Everything else in the catalogue is countable: a streak, a total, a type seen.
A note is freeform, and counting its words tells you how long it is rather than
what it says. These are the ones that need the meaning, and they are deliberately
the only part of the app that spends an API call.

Three properties make them affordable and trustworthy:

* **One call per note.** Every prototype is embedded when the catalogue is
  loaded, so a submission is a single embedding and then pure arithmetic.
* **Cheap guards first.** An achievement can require a word count, a line count
  or a length. Those are checked before the score is consulted, so a two-word
  "gut pain" never competes with a love poem for the same vector.
* **A margin, not just a floor.** A note that scores above several thresholds at
  once unlocks all of them. Requiring the winner to beat the runner-up by a
  margin means only an unambiguous note unlocks anything.

The thresholds are not guesses. `bm-tracker note-achievements calibrate` scores a
labelled corpus and reports, per achievement, whether the positives separate from
the negatives at all — and says so when they do not, rather than emitting a
number that would fire on everything.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

DEFINITIONS_PATH: Final = Path(__file__).parent / "note_achievements.toml"

# craft-dashboard's production note, learned the hard way: on
# text-embedding-3-small, genuinely related text scores around 0.30-0.45, not
# the 0.70+ a "similarity" number suggests. Every default threshold here is in
# that band, and a threshold above 0.6 should be treated as a mistake until
# calibration says otherwise.
DEFAULT_THRESHOLD: Final = 0.38
# How far ahead of the second-best match the winner has to be. Without this, a
# note that is vaguely about several things unlocks all of them.
DEFAULT_MARGIN: Final = 0.03
# Below this, no achievement is considered at all. It costs nothing to keep and
# saves a note that says "milk" from competing.
MIN_THRESHOLD: Final = 0.30


class DefinitionError(ValueError):
    """Raised when a note-achievement definition is malformed."""


@dataclass(frozen=True, slots=True)
class Guards:
    """Cheap, deterministic conditions on the raw text.

    Checked before any similarity is consulted, so a guard that cannot be
    satisfied costs nothing.
    """

    min_chars: int = 0
    max_chars: int = 0
    min_words: int = 0
    min_lines: int = 0
    max_lines: int = 0

    def passes(self, text: str) -> bool:
        """Return whether the text clears every guard.

        Args:
            text: The note, as written.

        Returns:
            Whether it is worth scoring at all.

        """
        stripped = text.strip()
        if len(stripped) < self.min_chars:
            return False
        if self.max_chars and len(stripped) > self.max_chars:
            return False
        if len(stripped.split()) < self.min_words:
            return False
        lines = [line for line in stripped.splitlines() if line.strip()]
        if len(lines) < self.min_lines:
            return False
        return not (self.max_lines and len(lines) > self.max_lines)


@dataclass(frozen=True, slots=True)
class NoteAchievement:
    """One achievement, and the text that earns it."""

    key: str
    name: str
    description: str
    tier: str
    points: int
    # The sentence that is embedded. Written to describe the *thing*, not to
    # share vocabulary with the notes it should match — sharing words is what a
    # lexical matcher does, and this is supposed to be better than that.
    semantic: str
    # Concrete examples, also embedded. They are the main lever on precision: an
    # example close to a real note teaches the geometry of that note, which a
    # description alone cannot.
    examples: tuple[str, ...] = ()
    guards: Guards = field(default_factory=Guards)
    threshold: float = DEFAULT_THRESHOLD
    margin: float = DEFAULT_MARGIN

    @property
    def prototypes(self) -> tuple[str, ...]:
        """Return every text embedded for this achievement."""
        return (self.semantic, *self.examples)


def load(path: Path | None = None) -> tuple[NoteAchievement, ...]:
    """Read the note-achievement catalogue.

    Args:
        path: An alternative catalogue file, for tests.

    Returns:
        The definitions, in file order.

    Raises:
        DefinitionError: If the file is missing, malformed, or names a
            threshold outside the band the model actually produces.

    """
    source = path or DEFINITIONS_PATH
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        msg = f"Note-achievement catalogue not found: {source}"
        raise DefinitionError(msg) from exc
    except tomllib.TOMLDecodeError as exc:
        msg = f"Note-achievement catalogue is not valid TOML: {exc}"
        raise DefinitionError(msg) from exc

    entries = data.get("note_achievement", [])
    if not isinstance(entries, list) or not entries:
        msg = "Catalogue defines no note achievements."
        raise DefinitionError(msg)

    seen: set[str] = set()
    built: list[NoteAchievement] = []
    for raw in entries:
        achievement = _compile(raw, seen)
        seen.add(achievement.key)
        built.append(achievement)
    return tuple(built)


def _compile(raw: object, seen: set[str]) -> NoteAchievement:
    """Validate and build one definition.

    Args:
        raw: The table from the catalogue.
        seen: Keys already used, so a duplicate is caught here.

    Returns:
        The compiled definition.

    Raises:
        DefinitionError: If anything required is missing or out of range.

    """
    # tomllib hands back plain dicts, but the catalogue is untrusted input and
    #  keeps the checker honest about everything that follows.
    if not isinstance(raw, dict):
        msg = f"Malformed note achievement: {raw!r}"
        raise DefinitionError(msg)
    required = {"key", "name", "description", "tier", "points", "semantic"}
    if not required <= set(raw):
        msg = f"Note achievement is missing {sorted(required - set(raw))}: {raw!r}"
        raise DefinitionError(msg)
    key = str(raw["key"])
    if key in seen:
        msg = f"Duplicate note achievement key: {key!r}"
        raise DefinitionError(msg)

    threshold = float(raw.get("threshold", DEFAULT_THRESHOLD))
    if not 0.0 < threshold < 1.0:
        msg = f"{key!r}: threshold must be between 0 and 1, got {threshold}"
        raise DefinitionError(msg)
    if threshold < MIN_THRESHOLD:
        # Not fatal, but worth refusing: below this the only thing separating a
        # match from noise is luck.
        msg = (
            f"{key!r}: threshold {threshold} is below {MIN_THRESHOLD}, where this "
            "model cannot separate a match from noise."
        )
        raise DefinitionError(msg)

    guard_raw = raw.get("guards", {})
    if not isinstance(guard_raw, dict):
        msg = f"{key!r}: guards must be a table."
        raise DefinitionError(msg)

    return NoteAchievement(
        key=key,
        name=str(raw["name"]),
        description=str(raw["description"]),
        tier=str(raw["tier"]),
        points=int(raw["points"]),
        semantic=str(raw["semantic"]),
        examples=tuple(str(e) for e in raw.get("examples", [])),
        guards=Guards(
            min_chars=int(guard_raw.get("min_chars", 0)),
            max_chars=int(guard_raw.get("max_chars", 0)),
            min_words=int(guard_raw.get("min_words", 0)),
            min_lines=int(guard_raw.get("min_lines", 0)),
            max_lines=int(guard_raw.get("max_lines", 0)),
        ),
        threshold=threshold,
        margin=float(raw.get("margin", DEFAULT_MARGIN)),
    )
