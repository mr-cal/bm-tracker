# The achievement icons

120 drawings, one per achievement, kept as source rather than as 120 committed
blobs you cannot review.

    python -m tools.icons                 # write the SVGs
    python -m tools.icons --sheet         # ...and a contact sheet at /tmp/icons.html

`icons.py` is the drawings. `source.py` owns the wrapper — the `svg` element,
`currentColor`, the 1.7 stroke, the round caps — so that the part which has to
be identical across the set is written once. `sheet.py` puts all of them on one
grid.

**The contact sheet is not optional.** `tests/unit/test_achievement_icons.py`
asserts the mechanical invariants: one drawing per achievement, no two with the
same path data, every file present and nothing stale, everything on the 24x24
grid. It does not render a pixel, and it cannot: the previous set passed all of
those checks while containing two byte-identical SVGs under different names
and five separate flames. Two icons can have entirely different path data and
still be indistinguishable at 40px. Only a grid catches that, and the grid is
one command away.

Run it after every batch. Nine of the first hundred-and-twenty had to be redrawn
because of what it showed, and every one of them looked fine in isolation:

- Leap Day was an alarm clock, and the Commuter's was already one
- Groundhog Day was an eye
- Friday the Thirteenth was a house
- The Blatherer was a sun
- One Of Everything was a second star

