"""add urgent to bm entries

Revision ID: fabf589e7960
Revises: b58f0a0c4633
Create Date: 2026-09-28 13:22:26.301931

Urgency is a boolean the user ticks, like `spicy` — not a derivation from how
long it took to log the entry. Nullable and not backfilled: an existing BM has
no recorded urgency, and inventing one would put a claim about someone's body
in the database on their behalf.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fabf589e7960"
down_revision: str | None = "b58f0a0c4633"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    with op.batch_alter_table("bm_entries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("urgent", sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Revert the migration."""
    with op.batch_alter_table("bm_entries", schema=None) as batch_op:
        batch_op.drop_column("urgent")
