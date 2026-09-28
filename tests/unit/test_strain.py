"""Tests for the strain scale.

Strain is the one field whose "absent" case matters. A null means "nobody
recorded it", which is a different claim from "it was easy", and the parse has to
keep those apart: an empty field is a real answer, a nonsense one is a bug.
"""

from __future__ import annotations

import pytest
from bm_tracker import strain


def test_the_scale_has_three_levels() -> None:
    """Three rungs, one to three."""
    assert [level.value for level in strain.STRAIN_SCALE] == [1, 2, 3]
    assert all(level.label and level.plain for level in strain.STRAIN_SCALE)


@pytest.mark.parametrize("value", [1, 2, 3])
def test_valid_levels_round_trip(value: int) -> None:
    """Every level parses back to itself."""
    assert strain.parse_strain(str(value)) == value
    assert strain.is_valid_strain(value)
    assert strain.get_level(value).value == value


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_blank_means_not_recorded(raw: str | None) -> None:
    """An empty field is an answer, not an error, and is not level 1."""
    assert strain.parse_strain(raw) is None


@pytest.mark.parametrize("raw", ["0", "4", "-1", "hard", "1.5", "two"])
def test_nonsense_is_rejected(raw: str) -> None:
    """A value that is present but invalid is a form bug, and says so."""
    with pytest.raises(ValueError, match="strain"):
        strain.parse_strain(raw)


def test_null_is_not_the_same_as_easy() -> None:
    """The distinction the field exists to preserve."""
    assert strain.parse_strain("") is not strain.parse_strain("1")
    assert strain.get_level(1).label == "Easy"
