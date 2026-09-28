"""How hard a bowel movement was to pass.

Three levels, because the whole point is that it takes one tap. Bristol has
seven rungs because the differences between them are clinically meaningful;
strain is a felt quantity with three distinguishable answers, and a seven-point
scale of it would be pretending to more precision than anyone has.

This exists despite §2.2 of the plan, which dropped strain to keep the logging
form to four fields. That reasoning still holds — the form is used in a hurry,
usually in a bathroom — so strain is deliberately last in the field order and
optional, and a null means "not recorded" rather than "no effort". The plan has
been amended to say so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

STRAIN_MIN: Final = 1
STRAIN_MAX: Final = 3


@dataclass(frozen=True, slots=True)
class StrainLevel:
    """One rung of the strain scale."""

    value: int
    label: str
    plain: str


STRAIN_SCALE: Final[tuple[StrainLevel, ...]] = (
    StrainLevel(1, "Easy", "Came out on its own."),
    StrainLevel(2, "Some effort", "Needed a bit of pushing."),
    StrainLevel(3, "Hard", "Took real effort."),
)

_BY_VALUE: Final[dict[int, StrainLevel]] = {
    level.value: level for level in STRAIN_SCALE
}


def is_valid_strain(value: int) -> bool:
    """Return whether a number is on the scale.

    Args:
        value: The candidate level.

    Returns:
        Whether it is in range 1-3.

    """
    return STRAIN_MIN <= value <= STRAIN_MAX


def get_level(value: int) -> StrainLevel:
    """Return the scale entry for a level.

    Args:
        value: The level, 1-3.

    Returns:
        The `StrainLevel`.

    Raises:
        ValueError: If the value is not on the scale.

    """
    entry = _BY_VALUE.get(value)
    if entry is None:
        msg = f"{value} is not a strain level."
        raise ValueError(msg)
    return entry


def parse_strain(value: str | None) -> int | None:
    """Parse a submitted strain level.

    Strain is optional, so an empty field is a legitimate answer meaning "not
    recorded" — distinct from level 1. A field that is present but nonsense is
    still an error, because that is a form bug rather than a choice.

    Args:
        value: The raw form value.

    Returns:
        The parsed level, or None if the field was left blank.

    Raises:
        ValueError: If it is neither blank nor a valid level.

    """
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        msg = "Pick a strain level, or leave it blank."
        raise ValueError(msg) from exc
    if not is_valid_strain(parsed):
        msg = "Pick a strain level, or leave it blank."
        raise ValueError(msg)
    return parsed
