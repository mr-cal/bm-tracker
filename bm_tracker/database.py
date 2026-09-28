"""Database engine construction and per-connection SQLite configuration.

SQLite needs three PRAGMAs set on every connection, and none of them are the
default. `foreign_keys` in particular is off unless asked for, which makes
`ON DELETE CASCADE` a no-op and orphans rows with no error at all.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from sqlalchemy.engine.interfaces import DBAPIConnection
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# Waits rather than raising "database is locked" when another connection holds a
# write lock. Writes in this app are short, so a brief wait is the right answer.
BUSY_TIMEOUT_MS = 5000


def _ensure_parent_directory(database_url: str) -> None:
    """Create the directory holding the SQLite file, if the URL is a file path.

    A path is used rather than a connection string locally so that `make dev`
    works from a clean checkout without a hand-created `data/` directory.
    """
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return

    raw_path = database_url.removeprefix(prefix)
    if not raw_path or raw_path == ":memory:":
        return

    path = Path(raw_path)
    if path.parent != Path():
        path.parent.mkdir(parents=True, exist_ok=True)


def _apply_pragmas(engine: AsyncEngine) -> None:
    """Register the connection-level PRAGMAs against a new engine.

    Applied on every new DBAPI connection rather than once at startup, because
    SQLite scopes each of these to a single connection and the pool opens more
    than one.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(
        dbapi_connection: DBAPIConnection,
        # SQLAlchemy does not export the record type publicly. The argument is
        # unused here, so `object` is honest without reaching into internals.
        _record: object,
    ) -> None:
        cursor = dbapi_connection.cursor()
        try:
            # Readers must not block the writer, or a dashboard read during a
            # log write raises "database is locked".
            cursor.execute("PRAGMA journal_mode=WAL")
            # Off by default in SQLite. Without this, ON DELETE CASCADE from
            # daily_logs to bm_entries never fires and orphans accumulate.
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()


def get_engine(database_url: str) -> AsyncEngine:
    """Create an async SQLite engine with the required PRAGMAs applied.

    No pool sizing is passed. SQLite serialises writers, and the pools
    SQLAlchemy selects for it either reject `pool_size` outright or gain
    nothing from it: `StaticPool` for an in-memory database, and
    `AsyncAdaptedQueuePool` for a file. The app runs a single worker precisely
    because a second one would only contend for the same write lock.

    Args:
        database_url: SQLAlchemy async URL, e.g. `sqlite+aiosqlite:///./app.db`.

    Returns:
        A configured `AsyncEngine`.

    """
    _ensure_parent_directory(database_url)
    engine = create_async_engine(database_url, pool_pre_ping=True, echo=False)
    _apply_pragmas(engine)
    return engine


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine.

    Args:
        engine: The async engine to bind sessions to.

    Returns:
        An `async_sessionmaker` producing `AsyncSession` instances.

    """
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def get_session_dependency(
    factory: async_sessionmaker[AsyncSession],
) -> Callable[[], AsyncIterator[AsyncSession]]:
    """Build a FastAPI dependency yielding a session from the given factory.

    Returns:
        An async generator function suitable for `Depends`.

    """

    async def _get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    return _get_session


async def check_database(engine: AsyncEngine) -> bool:
    """Return whether the database answers a trivial query.

    Used by the health endpoint. Deliberately reports only a boolean: the
    endpoint is unauthenticated, so it must not surface driver names, file paths
    or error text. See plans/plan-01-bootstrapping.md section 3.6.
    """
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Database health check failed", exc_info=True)
        return False
    return True
