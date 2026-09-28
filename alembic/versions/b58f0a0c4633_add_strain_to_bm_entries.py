"""add strain to bm entries

Revision ID: b58f0a0c4633
Revises: 2ac899a1e23f
Create Date: 2026-09-28 13:06:06.302561

Strain is nullable and is not backfilled. An existing BM predates the field, and
asserting a strain level for it would be inventing data rather than migrating
it; NULL reads as "not recorded", which is the honest answer and is distinct
from level 1, "was easy".

The CHECK constraint is applied in the same batch as the column. SQLite cannot
add a constraint to an existing table without rebuilding it, and Alembic's batch
mode does that rebuild once for both operations. Autogenerate would only have
emitted the column, leaving the constraint on the model but not in the database.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b58f0a0c4633"
down_revision: str | None = "2ac899a1e23f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STRAIN_MIN = 1
STRAIN_MAX = 3


def upgrade() -> None:
    """Apply the migration."""
    with op.batch_alter_table("bm_entries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("strain", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_bm_entries_strain_range",
            f"strain IS NULL OR strain BETWEEN {STRAIN_MIN} AND {STRAIN_MAX}",
        )


def downgrade() -> None:
    """Revert the migration."""
    with op.batch_alter_table("bm_entries", schema=None) as batch_op:
        batch_op.drop_constraint("ck_bm_entries_strain_range", type_="check")
        batch_op.drop_column("strain")
