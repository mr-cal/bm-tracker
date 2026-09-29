"""Working out what the thresholds should be, and whether they can be.

A threshold picked by eye is a number that either fires on everything or on
nothing, and you cannot tell which without testing it. So this scores a labelled
corpus — positives that *should* match, and a shared pool of negatives that
must not — and reports the two distributions side by side.

The result worth reading is not the suggested number. It is the verdict:

* **Separated** — the worst positive still beats the best negative. Any threshold
  between them works, and the midpoint is suggested.
* **Overlapping** — a negative scores higher than a positive. The achievement
  does not work as written, and no threshold will fix it: the fix is a different
  description, more examples, or a guard. Saying so is the point.
* **Dead** — nothing clears the bar even for the positives.

Precision is the bias throughout. A false positive is permanent and public: it
sits on the leaderboard and on the achievements page where your friends can see
it, forever. A false negative costs you one achievement and is never visible to
anyone. So the suggested threshold sits above the midpoint, nearer the worst
positive than the midpoint, and never below `MIN_THRESHOLD`.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from bm_tracker.notes.achievements import MIN_THRESHOLD, NoteAchievement
from bm_tracker.notes.embeddings import cosine

CALIBRATION_PATH: Final = Path(__file__).parent / "calibration.toml"

#: Headroom below this is small enough that one odd note could flip it.
TIGHT_GAP: Final = 0.05

SEPARATED: Final = "separated"
OVERLAPPING: Final = "overlapping"
DEAD: Final = "dead"
TIGHT: Final = "tight"


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the corpus says about one achievement."""

    key: str
    name: str
    verdict: str
    # The lowest score any positive reached, and the highest any negative did.
    worst_positive: float
    best_negative: float
    current: float
    suggested: float
    note: str

    @property
    def separable(self) -> bool:
        """Return whether any threshold separates the two groups."""
        return self.verdict in (SEPARATED, TIGHT)


def load_corpus(path: Path | None = None) -> tuple[dict[str, list[str]], list[str]]:
    """Read the labelled corpus.

    Args:
        path: An alternative corpus file, for tests.

    Returns:
        Positives keyed by achievement key, and the shared negative pool.

    """
    source = path or CALIBRATION_PATH
    data = tomllib.loads(source.read_text(encoding="utf-8"))
    positives = {
        str(key): [str(text) for text in table.get("values", [])]
        for key, table in data.get("positives", {}).items()
    }
    negatives = [str(text) for text in data.get("negatives", [])]
    return positives, negatives


async def calibrate(
    matcher,  # noqa: ANN001 - the protocol, spelled out in the type alias below
    definitions: tuple[NoteAchievement, ...],
    corpus_path: Path | None = None,
) -> list[Verdict]:
    """Score every achievement against the corpus and judge each one.

    Args:
        matcher: A prepared matcher, so prototypes are already embedded.
        definitions: The catalogue to judge.
        corpus_path: An alternative corpus file, for tests.

    Returns:
        One verdict per achievement, worst first, so the ones that need work are
        at the top.

    """
    positives, negatives = load_corpus(corpus_path)
    await matcher.prepare()

    results = [
        await _judge(matcher, definition, positives, negatives)
        for definition in definitions
    ]
    results.sort(key=lambda v: (v.separable, v.worst_positive))
    return results


async def _judge(
    matcher,  # noqa: ANN001
    definition: NoteAchievement,
    positives: dict[str, list[str]],
    negatives: list[str],
) -> Verdict:
    """Score one achievement's positives and negatives.

    Args:
        matcher: A prepared matcher.
        definition: The achievement to judge.
        positives: Labelled positives by key.
        negatives: The shared negative pool.

    Returns:
        The verdict.

    """
    mine = positives.get(definition.key, [])
    # Only examples that clear the guard can ever match, so testing a positive
    # the guard would have rejected anyway is measuring the wrong thing.
    usable = [text for text in mine if definition.guards.passes(text)]
    guard_rejected = len(mine) - len(usable)
    if not usable:
        return Verdict(
            key=definition.key,
            name=definition.name,
            verdict=DEAD,
            worst_positive=0.0,
            best_negative=0.0,
            current=definition.threshold,
            suggested=definition.threshold,
            note="every labelled example fails its own guard; the corpus or the "
            "guard is wrong",
        )

    # One embedding call for the whole batch, which is why calibration is
    # affordable and per-note matching is not.
    positive_scores, negative_scores = await _score_all(
        matcher,
        definition,
        usable,
        [n for n in negatives if definition.guards.passes(n)],
    )

    worst_positive = min(positive_scores)
    best_negative = max(negative_scores, default=0.0)

    if worst_positive < MIN_THRESHOLD:
        verdict, note = (
            DEAD,
            (
                f"the best a labelled example manages is {worst_positive:.2f}, below "
                f"the {MIN_THRESHOLD} floor; the description does not describe these "
                "notes"
            ),
        )
        suggested = definition.threshold
    elif best_negative >= worst_positive:
        verdict, note = (
            OVERLAPPING,
            (
                f"a negative scores {best_negative:.2f}, above the worst positive at "
                f"{worst_positive:.2f}; no threshold separates them. Needs a different "
                "description, more examples, or a stricter guard"
            ),
        )
        # Above both, so nothing false fires even though it is a poor threshold.
        suggested = max(best_negative, MIN_THRESHOLD) + 0.02
    else:
        midpoint = (worst_positive + best_negative) / 2
        # Biased towards the positives, because a miss is cheaper than a
        # false unlock that is public and permanent.
        suggested = round(worst_positive - (worst_positive - midpoint) * 0.35, 3)
        gap = worst_positive - best_negative
        if gap < TIGHT_GAP:
            verdict, note = (
                TIGHT,
                (
                    f"only {gap:.3f} of headroom; a single odd note could flip it. "
                    "Prefer a stricter guard over a lower threshold"
                ),
            )
        else:
            verdict, note = SEPARATED, f"{gap:.3f} of headroom"
        if guard_rejected:
            note += f"; the guard rejected {guard_rejected} of its own examples"

    return Verdict(
        key=definition.key,
        name=definition.name,
        verdict=verdict,
        worst_positive=round(worst_positive, 4),
        best_negative=round(best_negative, 4),
        current=definition.threshold,
        suggested=round(min(suggested, 0.99), 3),
        note=note,
    )


async def _score_all(
    matcher,  # noqa: ANN001
    definition: NoteAchievement,
    positives: list[str],
    negatives: list[str],
) -> tuple[list[float], list[float]]:
    """Return the best score each text reaches against one achievement.

    The best rather than the mean, because matching is existential: a note is
    either this achievement or it is not, and one strongly-matching example
    alongside three weak ones still counts.

    Args:
        matcher: A prepared matcher, so prototypes are already embedded.
        definition: The achievement being judged.
        positives: Its labelled examples that clear their own guard.
        negatives: The shared negatives that clear that same guard.

    Returns:
        Scores for the positives and for the negatives, in order.

    """
    texts = [*positives, *negatives]
    if not texts:
        return [], []
    vectors = await matcher.embedder.embed(texts)
    prototypes = matcher.prototype_vectors(definition.key)
    scored = [
        max((cosine(vector, p) for p in prototypes), default=0.0) for vector in vectors
    ]
    return scored[: len(positives)], scored[len(positives) :]
