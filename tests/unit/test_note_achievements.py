"""Tests for the note-achievement engine.

Nothing here calls a network. The matcher takes an `Embedder`, and the whole
point of that being a protocol is that the interesting behaviour — guards,
thresholds, margins, the one-call rule — can be tested hermetically.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bm_tracker.notes import achievements, calibration
from bm_tracker.notes.embeddings import cosine
from bm_tracker.notes.match import Matcher

CATALOGUE = achievements.load()


class FakeEmbedder:
    """An embedder that scores text by keyword overlap, with no network.

    Crude, and enough: the tests are about the arithmetic and the ordering, not
    about whether a bag of words is a good sentence encoder.
    """

    def __init__(self, vocabulary: dict[str, set[str]]) -> None:
        self.vocabulary = vocabulary

    @property
    def identity(self) -> str:
        return "fake"

    async def embed(self, texts):
        vectors = []
        for text in texts:
            words = {w.strip(".,!?").lower() for w in text.split()}
            vector = [0.0] * (len(self.vocabulary) + 1)
            for index, terms in enumerate(self.vocabulary.values()):
                overlap = len(words & terms)
                if overlap:
                    vector[index] = overlap / max(len(terms), 1)
            norm = sum(v * v for v in vector) ** 0.5
            vectors.append([v / norm for v in vector] if norm else vector)
        return vectors


def test_the_catalogue_loads_and_is_the_size_we_intend() -> None:
    assert len(CATALOGUE) >= 30
    assert len({a.key for a in CATALOGUE}) == len(CATALOGUE), "duplicate keys"


def test_every_threshold_is_in_the_band_this_model_produces() -> None:
    """Related text lands at 0.30-0.45 here, not 0.70.

    craft-dashboard learned that in production. A threshold above it is not
    "strict", it is "never fires", and the loader refuses one rather than
    letting it look deliberate.
    """
    for definition in CATALOGUE:
        assert 0.30 <= definition.threshold <= 0.60, definition.key
        assert definition.semantic, f"{definition.key} has nothing to embed"


def test_a_threshold_below_the_floor_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text(
        '[[note_achievement]]\nkey="k"\nname="N"\ndescription="d"\n'
        'tier="common"\npoints=2\nsemantic="s"\nthreshold=0.1\n'
    )
    with pytest.raises(achievements.DefinitionError, match="below"):
        achievements.load(bad)


def test_every_definition_has_a_labelled_positive() -> None:
    """Calibration needs one; without it the tool cannot judge anything."""
    positives, negatives = calibration.load_corpus()
    assert negatives, "a corpus with no negatives measures nothing"
    for definition in CATALOGUE:
        assert positives.get(definition.key), f"{definition.key} has no example"


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        ("one line", True),
        # Over the character cap, so it never reaches the line test at all.
        ("a whole line of text", False),
        # Short enough for the cap, but two lines.
        ("a\nb", False),
    ],
)
def test_guards_are_checked_before_any_score(text: str, expect: bool) -> None:
    """Cheap, exact, and free — so they are asked first."""
    guards = achievements.Guards(max_chars=9, max_lines=1)
    assert guards.passes(text) is expect


def test_cosine_of_identical_vectors_is_one() -> None:
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0, "a zero vector must not divide"


async def test_a_note_costs_exactly_one_embedding_call() -> None:
    """The whole point: one call per note, however big the catalogue is."""
    calls: list[int] = []

    class Counting(FakeEmbedder):
        async def embed(self, texts):
            calls.append(len(texts))
            return await super().embed(texts)

    matcher = Matcher(
        embedder=Counting({"a": {"love"}, "b": {"poem"}}), definitions=CATALOGUE[:6]
    )
    await matcher.prepare()
    calls.clear()
    await matcher.score("a love poem about you and me")
    assert calls == [1], f"expected one call for the note, got {calls}"


async def test_a_note_too_short_to_mean_anything_is_never_embedded() -> None:
    """ "no" is below the floor, so it costs no call and matches nothing.

    Per-achievement guards cannot cover this: most have no minimum, so a
    two-letter note is still eligible for thirty of them. Without a floor the
    call gets spent to discover what the length already said.
    """
    calls: list[int] = []

    class Counting(FakeEmbedder):
        async def embed(self, texts):
            calls.append(len(texts))
            return await super().embed(texts)

    matcher = Matcher(embedder=Counting({"a": {"love"}}), definitions=CATALOGUE)
    await matcher.prepare()
    calls.clear()

    results = await matcher.score("no")

    assert calls == [], f"a two-letter note cost {len(calls)} calls"
    assert not any(s.eligible for s in results)
