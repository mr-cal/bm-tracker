"""Matching a note against the catalogue, for exactly one embedding call.

The order of operations is the design:

1. **Guards.** An achievement whose cheap conditions the note fails is dropped
   before it is scored. This is not only about cost — one API call covers the
   whole catalogue regardless — it is about precision. A two-word note cannot
   match "a poem about romantic love" however well it embeds, and removing it
   early means it cannot come second and eat the margin either.
2. **One embedding.** The note is embedded once, whatever the catalogue size.
3. **Local cosine, per prototype.** Every definition contributes its description
   and its examples; the best similarity to any of them is that definition's
   score. Examples are what make this precise: a description says what the thing
   *is*, an example sits where a real note sits.
4. **Floor and margin.** The winner has to clear its own threshold *and* beat
   the runner-up. The margin is the part that stops a note about several things
   unlocking all of them at once.

Everything after step two is arithmetic on cached vectors, so the same note
always produces the same answer, and calibrating a new threshold does not cost
anything at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bm_tracker.notes.achievements import load
from bm_tracker.notes.embeddings import EmbeddingError, cosine

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from bm_tracker.notes.achievements import NoteAchievement
    from bm_tracker.notes.embeddings import Embedder

CACHE_VERSION = 1

# Below this, no note is worth embedding at all. Per-achievement guards cannot
# cover it — most have no minimum, so a two-letter note is still eligible for
# thirty of them, and the call would be spent to discover that. Which is fine,
# except it is an API call spent discovering it.
MIN_NOTE_CHARS = 12

__all__ = [
    "CACHE_VERSION",
    "Match",
    "Matcher",
    "Scored",
    "cosine",
]


@dataclass(frozen=True, slots=True)
class Match:
    """One achievement a note earned, and how strongly."""

    key: str
    name: str
    description: str
    tier: str
    points: int
    score: float

    @property
    def percent(self) -> int:
        """Return the score as a whole percentage, for the record."""
        return round(self.score * 100)


@dataclass(frozen=True, slots=True)
class Scored:
    """A definition's score against a note, whether or not it won."""

    key: str
    score: float
    eligible: bool


class Matcher:
    """The note-achievement engine: prototypes, then one call per note.

    The prototype vectors are embedded once and cached on disk, keyed by the
    embedder's identity and a hash of the catalogue. Without that cache, adding
    a new achievement would cost a hundred API calls the first time somebody
    logged anything, and a cache keyed on nothing but the definitions would go
    quietly stale the day the model changed.
    """

    def __init__(
        self,
        *,
        embedder: Embedder,
        definitions: Sequence[NoteAchievement] | None = None,
        cache_path: Path | None = None,
    ) -> None:
        """Build a matcher and load or build its prototypes.

        Args:
            embedder: What turns text into vectors.
            definitions: The catalogue. Loaded from the shipped file if omitted.
            cache_path: Where to cache prototype vectors. No caching if None.

        """
        self.embedder = embedder
        self.definitions = tuple(definitions) if definitions is not None else load()
        self.cache_path = cache_path
        self._prototypes: dict[str, list[list[float]]] = {}
        self._meta: str = ""

    @property
    def catalogue_digest(self) -> str:
        """Return a digest of the definitions, for the cache key."""
        import hashlib  # noqa: PLC0415

        hasher = hashlib.sha256()
        for definition in self.definitions:
            hasher.update(definition.key.encode())
            hasher.update(b"\0")
            for text in definition.prototypes:
                hasher.update(text.encode())
                hasher.update(b"\0")
            hasher.update(f"{definition.threshold}".encode())
        return hasher.hexdigest()[:16]

    async def prepare(self) -> None:
        """Make sure every prototype has a vector, embedding if needed.

        This is the expensive call, and it happens when the catalogue changes
        rather than when somebody logs.
        """
        if self._prototypes:
            return

        cached = self._read_cache()
        wanted: list[str] = []
        texts: list[str] = []
        for definition in self.definitions:
            cached_for = cached.get(definition.key) if cached else None
            if cached_for and len(cached_for) == len(definition.prototypes):
                self._prototypes[definition.key] = cached_for
                continue
            wanted.append(definition.key)
            texts.extend(definition.prototypes)

        if texts:
            vectors = await self.embedder.embed(texts)
            cursor = 0
            for key in wanted:
                definition = self._by_key(key)
                span = len(definition.prototypes)
                self._prototypes[key] = vectors[cursor : cursor + span]
                cursor += span
            self._write_cache()

    def prototype_vectors(self, key: str) -> list[list[float]]:
        """Return the cached prototype vectors for one achievement.

        Args:
            key: The achievement key.

        Returns:
            The vectors, empty if the catalogue has not been prepared.

        """
        return self._prototypes.get(key, [])

    def _by_key(self, key: str) -> NoteAchievement:
        """Return one definition by key.

        Args:
            key: The achievement key.

        Returns:
            The definition.

        Raises:
            KeyError: If the catalogue does not have it, which would mean the
                cache and the catalogue disagree.

        """
        return next(d for d in self.definitions if d.key == key)

    def _read_cache(self) -> dict[str, list[list[float]]]:
        """Return the cached prototypes, or nothing if the cache is stale.

        Returns:
            Key to prototype vectors, empty when the cache cannot be trusted.

        """
        if not self.cache_path or not self.cache_path.is_file():
            return {}
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if payload.get("version") != CACHE_VERSION:
            return {}
        if payload.get("embedder") != self.embedder.identity:
            return {}
        if payload.get("digest") != self.catalogue_digest:
            return {}
        cached = payload.get("prototypes", {})
        return cached if isinstance(cached, dict) else {}

    def _write_cache(self) -> None:
        """Save the prototypes, ignoring a failure to write.

        A read-only filesystem costs a hundred API calls once and then works
        from memory; failing the log to persist a cache would be the wrong
        trade.
        """
        if not self.cache_path:
            return
        payload = {
            "version": CACHE_VERSION,
            "embedder": self.embedder.identity,
            "digest": self.catalogue_digest,
            "prototypes": self._prototypes,
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:  # pragma: no cover - a cache is never load-bearing
            pass

    async def score(self, text: str) -> list[Scored]:
        """Score a note against every definition, eligible or not.

        Args:
            text: The note, as written.

        Returns:
            One `Scored` per definition, best first. Definitions whose guards the
            note fails are included with `eligible=False` and a score of 0.0, so
            the caller can see what was considered and rejected.

        Raises:
            EmbeddingError: If the note could not be embedded.

        """
        await self.prepare()
        if not self.definitions:
            return []
        if len(text.strip()) < MIN_NOTE_CHARS:
            return [
                Scored(key=d.key, score=0.0, eligible=False) for d in self.definitions
            ]

        eligible = [d for d in self.definitions if d.guards.passes(text)]
        if not eligible:
            return [
                Scored(key=d.key, score=0.0, eligible=False) for d in self.definitions
            ]

        vector = (await self.embedder.embed([text]))[0]

        results: list[Scored] = []
        for definition in eligible:
            best = max(
                (
                    cosine(vector, prototype)
                    for prototype in self._prototypes.get(definition.key, [])
                ),
                default=0.0,
            )
            results.append(
                Scored(key=definition.key, score=round(best, 4), eligible=True)
            )

        results.extend(
            Scored(key=d.key, score=0.0, eligible=False)
            for d in self.definitions
            if not d.guards.passes(text)
        )

        results.sort(key=lambda s: s.score, reverse=True)
        return results

    async def match(self, text: str) -> list[Match]:
        """Return the achievements a note earns.

        At most one, by design. A note that is genuinely two things at once
        should earn both, and the way to earn both is to write two notes — the
        reward for clarity is getting told clearly.

        Args:
            text: The note, as written.

        Returns:
            The single best match, if it clears its threshold and its margin.

        Raises:
            EmbeddingError: If the note could not be embedded.

        """
        results = await self.score(text)
        viable = [r for r in results if r.eligible and r.score > 0.0]
        if not viable:
            return []

        best = viable[0]
        definition = self._by_key(best.key)
        if best.score < definition.threshold:
            return []
        if len(viable) > 1:
            margin = best.score - viable[1].score
            if margin < definition.margin:
                return []

        return [
            Match(
                key=definition.key,
                name=definition.name,
                description=definition.description,
                tier=definition.tier,
                points=definition.points,
                score=best.score,
            )
        ]

    async def try_match(self, text: str) -> list[Match]:
        """Return the matches, or nothing if the provider is unavailable.

        A note must never fail to be saved because a semantic bonus could not
        be computed. The achievement is the treat; the log is the job.

        Args:
            text: The note, as written.

        Returns:
            The match, or an empty list.

        """
        try:
            return await self.match(text)
        except EmbeddingError:
            return []
