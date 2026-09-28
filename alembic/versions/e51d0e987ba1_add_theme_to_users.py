"""add theme to users

Revision ID: e51d0e987ba1
Revises: fabf589e7960
Create Date: 2026-09-28 17:05:11.402118

Existing accounts are set to `light`, not `auto`. They have been rendering
light already — the app followed the operating system only to pick a value, and
there is no record of what any of them chose — so `auto` would be a claim about
a preference nobody ever expressed. `light` is what the app did for anyone whose
phone was not in dark mode, and it is the documented default.

The CHECK constraint is applied in the same batch as the column. SQLite cannot
add a constraint to an existing table without rebuilding it, and autogenerate
only emits the column, so the constraint would exist on the model and not in the
database.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e51d0e987ba1"
down_revision: str | None = "fabf589e7960"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

THEMES = ("auto", "dark", "light")


def upgrade() -> None:
    """Apply the migration."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("theme", sa.String(16), nullable=False, server_default="light")
        )
        batch_op.create_check_constraint(
            "ck_users_theme",
            "theme IN ('auto', 'dark', 'light')",
        )


def downgrade() -> None:
    """Revert the migration."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint("ck_users_theme", type_="check")
        batch_op.drop_column("theme")
