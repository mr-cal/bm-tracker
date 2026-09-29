"""Computing text embeddings, for achievements that read a note.

The app already has a rule engine for everything that can be counted: streaks,
totals, types seen. A note is freeform, and counting its words tells you only how
long it is. These achievements are the ones that need the *meaning* of what was
written, and this is the smallest thing that gets it.

Modelled on craft-dashboard's `EmbeddingClient`, which has been running against
OpenRouter in production: an OpenAI-compatible `/embeddings` endpoint, a Bearer
key, and graceful absence when no key is configured. That last part matters more
here than it does there. A missing key is the normal case for a private app, and
the whole note-achievement system switches itself off rather than failing a log.

Nothing here is a language model. It is one small vector per note and a cosine
similarity, which is what keeps it to a single API call per submission with every
comparison done locally against prototypes embedded ahead of time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

import httpx

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_PAYMENT_REQUIRED = 402
HTTP_FORBIDDEN = 403
# OpenAI-compatible endpoints reject very long inputs; the note is a sentence or
# two, but a pasted essay should truncate rather than 400 the whole log.
_MAX_INPUT_CHARS = 4000


class EmbeddingError(RuntimeError):
    """Raised when the embedding provider could not be used."""


class Embedder(Protocol):
    """Something that turns text into vectors.

    Kept as a protocol so the matcher and the calibration tool can be tested
    without a network, which is most of the reason this file is a class rather
    than a function call.
    """

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per input text, in order.

        Args:
            texts: The texts to embed.

        Returns:
            One vector each, in the same order as the inputs.

        """
        ...

    @property
    def identity(self) -> str:
        """Return what identifies this embedder, for cache keys.

        A cached prototype set is only valid for the embedder that made it, so
        the identity has to name the model and the dimensions as well as the
        endpoint.
        """
        ...


class OpenRouterEmbedder:
    """Compute embeddings through OpenRouter's OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        base_url: str = OPENROUTER_BASE_URL,
        model: str = "openai/text-embedding-3-small",
        api_key: str,
        dimensions: int = 1024,
    ) -> None:
        """Build a client.

        Args:
            base_url: The API root.
            model: The embedding model to use.
            api_key: The bearer token.
            dimensions: Vector width. text-embedding-3-small supports being
                narrowed, and a sixth of the width is a sixth of the payload for
                no measurable loss on this kind of comparison.

        Raises:
            EmbeddingError: If no key was given. There is no anonymous mode and
                pretending otherwise would fail later and less clearly.

        """
        if not api_key.strip():
            msg = "An API key is required to compute embeddings."
            raise EmbeddingError(msg)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.dimensions = dimensions
        self._http: httpx.AsyncClient | None = None

    @property
    def _client(self) -> httpx.AsyncClient:
        """Return the shared HTTP client, opening it on first use."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    @property
    def identity(self) -> str:
        """Return what identifies this embedder, for cache keys."""
        return f"{self.base_url}|{self.model}|{self.dimensions}"

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text, in order.

        Args:
            texts: The texts to embed.

        Returns:
            One vector each, in the same order as the inputs.

        Raises:
            EmbeddingError: If the provider refused or returned nonsense.

        """
        if not texts:
            return []
        clipped = [t[:_MAX_INPUT_CHARS] for t in texts]
        response = await self._client.post(
            f"{self.base_url}/embeddings",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json={
                "model": self.model,
                "input": list(clipped),
                "dimensions": self.dimensions,
            },
        )
        if response.is_error:
            detail = response.text[:300]
            if response.status_code in (HTTP_PAYMENT_REQUIRED, HTTP_FORBIDDEN):
                msg = f"Embedding quota or budget exhausted: {detail}"
            elif response.status_code == HTTP_BAD_REQUEST:
                msg = f"Embedding request rejected: {detail}"
            else:
                msg = f"Embedding request failed ({response.status_code}): {detail}"
            raise EmbeddingError(msg)

        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(clipped):
            msg = f"Embedding provider returned {len(data or [])} vectors for {len(clipped)} inputs."
            raise EmbeddingError(msg)
        # The API does not promise to answer in order; `index` is how it says
        # which is which, and getting this wrong would silently misattribute
        # every prototype.
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        return [list(item["embedding"]) for item in ordered]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Return the cosine similarity of two vectors.

    Args:
        left: One vector.
        right: The other, of the same length.

    Returns:
        The similarity, in -1 to 1. Zero vectors compare as 0.0 rather than
        dividing by zero, which would only happen if the provider returned
        nothing useful.

    """
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = sum(a * a for a in left) ** 0.5
    norm_right = sum(b * b for b in right) ** 0.5
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)
