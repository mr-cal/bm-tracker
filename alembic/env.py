"""Alembic migration environment."""

import os
from logging.config import fileConfig

from alembic import context
from bm_tracker.models import Base
from sqlalchemy import create_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importing the models package registers every table on Base.metadata, which is
# what --autogenerate compares the database against. Without it, autogenerate
# refuses to run.
target_metadata = Base.metadata

# Migrations are synchronous. The app uses the async aiosqlite driver, so the
# async prefix is stripped to reach the pysqlite one.
database_url = os.environ.get("DATABASE_URL", "sqlite:///./data/bm_tracker.db")
sync_url = database_url.replace("+aiosqlite", "").replace("+asyncpg", "")


def run_migrations_offline() -> None:
    """Run migrations without a live connection, emitting SQL."""
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = create_engine(sync_url)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=True,
            # SQLite cannot ALTER a column in place; batch mode rewrites the
            # table instead. Without this, a schema change that renames or
            # alters a column fails on the production database.
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
