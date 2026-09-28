"""Tests for the SQLite connection configuration.

These exist because the failure modes they cover are silent. A missing
`foreign_keys` pragma does not raise; it just stops `ON DELETE CASCADE` from
working, and the orphaned rows show up months later as a mystery.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bm_tracker.database import BUSY_TIMEOUT_MS, get_engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def _pragma_value(engine: AsyncEngine, name: str) -> str:
    """Return the value of a PRAGMA on a fresh connection from the pool.

    Opening a new connection each time is deliberate: PRAGMAs are per-connection
    in SQLite, so a check on the connection that set them proves nothing about
    the connections the pool opens afterwards.

    Args:
        engine: The engine to read from.
        name: The PRAGMA to read.

    Returns:
        The PRAGMA's value as a string.
    """
    async with engine.connect() as connection:
        result = await connection.execute(text(f"PRAGMA {name}"))
        return str(result.scalar())


async def test_journal_mode_is_wal(test_engine: AsyncEngine) -> None:
    """Readers must not block the writer, or a read during a write raises."""
    assert await _pragma_value(test_engine, "journal_mode") == "wal"


async def test_foreign_keys_is_enabled(test_engine: AsyncEngine) -> None:
    """SQLite leaves foreign keys off unless asked.

    Without this, `ON DELETE CASCADE` from daily_logs to bm_entries silently
    does nothing.
    """
    assert await _pragma_value(test_engine, "foreign_keys") == "1"


async def test_busy_timeout_is_set(test_engine: AsyncEngine) -> None:
    """A contended write should wait rather than fail immediately."""
    value = await _pragma_value(test_engine, "busy_timeout")
    assert int(value) == BUSY_TIMEOUT_MS


async def test_pragmas_apply_to_every_pooled_connection(
    test_engine: AsyncEngine,
) -> None:
    """The settings are per-connection, so a second connection must have them too.

    A single-connection check would pass even if the hook were registered
    against the wrong target and never fired again.
    """
    async with test_engine.connect() as first:
        await first.execute(text("SELECT 1"))

    values = [await _pragma_value(test_engine, "foreign_keys") for _ in range(3)]
    assert values == ["1", "1", "1"]


async def test_engine_creates_the_parent_directory(tmp_path: Path) -> None:
    """A clean checkout must not need a hand-created data/ directory."""
    target = tmp_path / "nested" / "app.db"
    engine = get_engine(f"sqlite+aiosqlite:///{target}")
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
    assert target.parent.is_dir()


@pytest.mark.parametrize(
    "url",
    [
        "sqlite+aiosqlite:///:memory:",
        "sqlite+aiosqlite:///bare.db",
    ],
)
async def test_urls_without_a_directory_are_handled(
    url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A memory URL, or one with no directory component, must not be mkdir'd.

    `sqlite+aiosqlite:///:memory:` has no filesystem path at all, and
    `sqlite+aiosqlite:///bare.db` sits in the current directory. Treating the
    first as a path would try to create a directory named `:memory:`.
    """
    monkeypatch.chdir(tmp_path)

    engine = get_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()

    assert not (tmp_path / ":memory:").exists()
