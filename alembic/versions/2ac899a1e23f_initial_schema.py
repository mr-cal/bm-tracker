"""Initial schema.

Seven tables. Three carry the design decisions that are expensive to change
later, so they are worth naming here:

- `daily_logs` is unique on (user_id, day), which is what makes "this day is
  logged" a single fact rather than a tally, and is what a "nothing today" day
  is: a row with n_bms = 0.
- `bm_entries` cascades from `daily_logs`, which only works because the app
  sets PRAGMA foreign_keys=ON on every connection. Without it this constraint
  is silently inert.
- `audit_log` has no foreign key on user_id on purpose: a deleted user's rows
  and the record that they were deleted must both survive the delete.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2ac899a1e23f"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_audit_log_action"), ["action"], unique=False
        )
        batch_op.create_index("ix_audit_log_at", ["at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_audit_log_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=60), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_users_username"), ["username"], unique=True
        )

    op.create_table(
        "celebration_seen",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("shown_count", sa.Integer(), nullable=False),
        sa.Column("last_shown_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "message_id"),
    )
    op.create_table(
        "achievement_unlocks",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("achievement_key", sa.String(length=64), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "achievement_key", "year"),
    )
    op.create_table(
        "daily_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("n_bms", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("logged_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("n_bms >= 0", name="ck_daily_logs_n_bms_non_negative"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "day", name="uq_daily_logs_user_day"),
    )
    with op.batch_alter_table("daily_logs", schema=None) as batch_op:
        batch_op.create_index(
            "ix_daily_logs_user_day", ["user_id", "day"], unique=False
        )

    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("invites", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_invites_token_hash"), ["token_hash"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_invites_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            "ix_invites_user_unused", ["user_id", "used_at"], unique=False
        )

    op.create_table(
        "user_facts",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("fact_key", sa.String(length=64), nullable=False),
        sa.Column("fact_value", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "fact_key"),
    )
    op.create_table(
        "bm_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("daily_log_id", sa.Integer(), nullable=False),
        sa.Column("occurred_local", sa.DateTime(), nullable=False),
        sa.Column("bristol_type", sa.Integer(), nullable=False),
        sa.Column("spicy", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "bristol_type BETWEEN 1 AND 7", name="ck_bm_entries_bristol_type_range"
        ),
        sa.ForeignKeyConstraint(
            ["daily_log_id"], ["daily_logs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("bm_entries", schema=None) as batch_op:
        batch_op.create_index("ix_bm_entries_daily_log", ["daily_log_id"], unique=False)


def downgrade() -> None:
    """Revert the migration."""
    with op.batch_alter_table("bm_entries", schema=None) as batch_op:
        batch_op.drop_index("ix_bm_entries_daily_log")

    op.drop_table("bm_entries")
    op.drop_table("user_facts")
    with op.batch_alter_table("invites", schema=None) as batch_op:
        batch_op.drop_index("ix_invites_user_unused")
        batch_op.drop_index(batch_op.f("ix_invites_user_id"))
        batch_op.drop_index(batch_op.f("ix_invites_token_hash"))

    op.drop_table("invites")
    with op.batch_alter_table("daily_logs", schema=None) as batch_op:
        batch_op.drop_index("ix_daily_logs_user_day")

    op.drop_table("daily_logs")
    op.drop_table("achievement_unlocks")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_username"))

    op.drop_table("users")
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_log_user_id"))
        batch_op.drop_index("ix_audit_log_at")
        batch_op.drop_index(batch_op.f("ix_audit_log_action"))

    op.drop_table("audit_log")
