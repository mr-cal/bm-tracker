"""Tests for the celebration copy and its rotation.

The catalogue itself is data and is trusted; what is tested is the machinery that
decides which line you see, and the mapping that decides which pool an event
draws from.
"""

from __future__ import annotations

import pytest
from bm_tracker import celebrate

# Every event the log route raises, plus the ones the reward screen can raise.
# Kept as a literal rather than scraped so that adding an event without mapping
# it is a failure here rather than a pool that quietly stops being used.
EVENTS = ("log_any", "log_none", "quick_entry", "note_added", "backfill", "streak")


def test_every_event_maps_to_a_pool_that_exists() -> None:
    """An unmapped event silently falls back, and the pool is then never seen.

    This is not hypothetical: `log_any` was missing from the mapping, so every
    plain log drew from the fallback instead and the largest pool in the
    catalogue never rendered once.
    """
    for event in EVENTS:
        pool = celebrate.POOL_FOR_EVENT.get(event)
        assert pool is not None, f"{event!r} is not mapped, so its pool is dead"
        assert celebrate.POOLS.get(pool), f"{event!r} maps to empty pool {pool!r}"


def test_a_plain_log_is_not_routed_to_the_fallback() -> None:
    """The general pool is the one a plain log should use."""
    assert celebrate.POOL_FOR_EVENT["log_any"] == "log_any"
    assert celebrate.POOL_FOR_EVENT["log_any"] != celebrate.DEFAULT_POOL


def test_the_blend_pool_exists_and_is_not_the_only_pool() -> None:
    assert celebrate.BLEND_POOL in celebrate.POOLS
    assert celebrate.BLEND_POOL != "log_any"


def test_every_pool_has_lines_and_every_line_is_usable() -> None:
    for name, messages in celebrate.POOLS.items():
        assert messages, f"pool {name!r} is empty"
        for message in messages:
            assert message.text.strip(), f"{message.id} is blank"
            assert len(message.text) <= 140, f"{message.id} will wrap badly"


@pytest.mark.parametrize(
    "slot", ["noting", "nothing_today", "strain_1", "strain_2", "strain_3"]
)
def test_every_variant_slot_is_populated(slot: str) -> None:
    assert celebrate._VARIANTS_BY_SLOT.get(slot), f"slot {slot!r} has no variants"


def test_the_noting_slot_has_enough_to_not_repeat() -> None:
    """Fifty-four headings means you see a new one on a form you open daily."""
    assert len(celebrate._VARIANTS_BY_SLOT["noting"]) >= 50
