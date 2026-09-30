"""add note themes to bm entries

Revision ID: b1c4e70a9f22
Revises: a85dd7a17a81
Every entry now records which note themes its text matched, so an achievement
can combine what was written with what was logged: a spicy entry that came
with a note about the curry, rather than a count of either.

Without this the two systems could not meet. The matcher knew what a note
said and the facts only knew how many entries there were, and the answer to
"was that note angry *and* was that entry spicy" was thrown away the moment
the unlock was decided.

A comma-separated list of note-achievement keys rather than a join table,
because it is read exactly once per entry when facts are built and never
queried by theme directly. Nullable, because an entry with no note — or one
written while no embedding key was configured — matched nothing.

Create Date: 2026-09-30 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c4e70a9f22"
down_revision: str | None = "a85dd7a17a81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    with op.batch_alter_table("bm_entries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("note_themes", sa.String(length=255)))


def downgrade() -> None:
    """Revert the migration."""
    with op.batch_alter_table("bm_entries", schema=None) as batch_op:
        batch_op.drop_column("note_themes")
