"""The Bristol stool scale and input validation.

Seven types in three rough bands: 1-2 hard, 3-4 normal, 5-7 loose to liquid.
The medical descriptions are the standard scale; the plain-language ones exist
because the interface has to be usable on a phone by someone in a hurry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

BRISTOL_MIN: Final = 1
BRISTOL_MAX: Final = 7

# The three consistency bands, as inclusive value ranges.
BAND_HARD_MAX: Final = 2
BAND_NORMAL_MAX: Final = 4


@dataclass(frozen=True, slots=True)
class BristolType:
    """One rung of the scale."""

    value: int
    label: str
    clinical: str
    plain: str

    @property
    def band(self) -> str:
        """Return the rough consistency band this type belongs to."""
        if self.value <= BAND_HARD_MAX:
            return "hard"
        if self.value <= BAND_NORMAL_MAX:
            return "normal"
        return "loose"


BRISTOL_SCALE: Final[tuple[BristolType, ...]] = (
    BristolType(
        1,
        "Type 1",
        "Separate hard lumps, like nuts",
        "Hard little lumps. Difficult to pass.",
    ),
    BristolType(
        2,
        "Type 2",
        "Lumpy and sausage-like",
        "Lumpy, like a sausage.",
    ),
    BristolType(
        3,
        "Type 3",
        "Sausage-shaped, smooth and soft",
        "Smooth and soft, sausage-shaped.",
    ),
    BristolType(
        4,
        "Type 4",
        "Like a snake, smooth and soft",
        "The classic. Smooth and soft.",
    ),
    BristolType(
        5,
        "Type 5",
        "Soft blobs with clear edges",
        "Soft blobs, easy to pass.",
    ),
    BristolType(
        6,
        "Type 6",
        "Mushy, fluffy, soft blobs",
        "Mushy and fluffy.",
    ),
    BristolType(
        7,
        "Type 7",
        "Entirely liquid, no solid parts",
        "Entirely liquid.",
    ),
)

_BY_VALUE: Final[dict[int, BristolType]] = {t.value: t for t in BRISTOL_SCALE}


def is_valid_type(value: int) -> bool:
    """Return whether a number is on the scale.

    Args:
        value: The candidate type.

    Returns:
        Whether it is in range 1-7.

    """
    return BRISTOL_MIN <= value <= BRISTOL_MAX


def get_type(value: int) -> BristolType:
    """Return the scale entry for a type.

    Args:
        value: The type, 1-7.

    Returns:
        The `BristolType`.

    Raises:
        ValueError: If the value is not on the scale.

    """
    entry = _BY_VALUE.get(value)
    if entry is None:
        msg = f"{value} is not a Bristol type."
        raise ValueError(msg)
    return entry


def parse_type(value: str | None) -> int:
    """Parse a submitted type.

    Args:
        value: The raw form value.

    Returns:
        The type, 1-7.

    Raises:
        ValueError: If it is missing or not on the scale.

    """
    if value is None:
        msg = "Pick a Bristol type."
        raise ValueError(msg)
    try:
        parsed = int(value)
    except ValueError as exc:
        msg = "Pick a Bristol type."
        raise ValueError(msg) from exc
    if not is_valid_type(parsed):
        msg = "Pick a Bristol type."
        raise ValueError(msg)
    return parsed
