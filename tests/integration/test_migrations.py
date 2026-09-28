"""Tests that the migration and the models agree, and that it is idempotent.

The unit tests build their schema with `Base.metadata.create_all`, so they would
keep passing even if the migration were wrong. These run the real Alembic path
against a throwaway database and compare what it produced with the models.

Deliberately synchronous: Alembic's API and `sqlite3` are synchronous, and
driving them from an async test would mean nesting two engines and two event
loops for no benefit.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from bm_tracker.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TABLES = {
    "achievement_unlocks",
    "audit_log",
    "bm_entries",
    "daily_logs",
    "invites",
    "user_facts",
    "users",
}


def _alembic_config(database: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Return an Alembic config pointed at a throwaway database.

    Args:
        database: The SQLite file to migrate.
        monkeypatch: Used to set DATABASE_URL for the duration of the test.

    Returns:
        A configured `Config`.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database}")
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return config


def _tables(database: Path) -> set[str]:
    """Return the table names in a SQLite file."""
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {row[0] for row in rows}


def _columns(database: Path, table: str) -> dict[str, dict]:
    """Return a mapping of column name to its PRAGMA info."""
    with sqlite3.connect(database) as connection:
        return {
            row[1]: {"type": row[2], "notnull": row[3]}
            for row in connection.execute(f"PRAGMA table_info({table})")
        }


def _check_constraints(database: Path) -> set[str]:
    """Return every CHECK constraint name in the database."""
    found: set[str] = set()
    with sqlite3.connect(database) as connection:
        for table in _tables(database):
            for row in connection.execute(f"PRAGMA index_list({table})"):
                if not row[2]:  # not a unique index
                    continue
            # CHECK constraint names are not exposed by any pragma, so read them
            # back from the stored CREATE TABLE statement.
            statement = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if statement and statement[0]:
                for token in statement[0].split():
                    if token.startswith("ck_"):
                        found.add(token.rstrip(",)"))
    return found


def test_migration_creates_every_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`alembic upgrade head` produces the full schema from nothing."""
    database = tmp_path / "migrated.db"

    command.upgrade(_alembic_config(database, monkeypatch), "head")

    assert _tables(database) >= EXPECTED_TABLES


def test_upgrade_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Running it twice is a no-op, because the container does exactly that.

    The Dockerfile runs `alembic upgrade head` on every start, so a migration
    that is not idempotent breaks on the second deploy.
    """
    database = tmp_path / "twice.db"
    config = _alembic_config(database, monkeypatch)

    command.upgrade(config, "head")
    before = _tables(database)
    command.upgrade(config, "head")

    assert _tables(database) == before


def test_downgrade_removes_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A migration you cannot reverse is a migration you cannot test."""
    database = tmp_path / "reversible.db"
    config = _alembic_config(database, monkeypatch)

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    assert not (EXPECTED_TABLES & _tables(database))


def test_migration_matches_the_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The migrated schema and `Base.metadata` must describe the same thing.

    This is the drift guard. The unit tests use `create_all`, so without this
    the two could diverge silently and only a real deploy would find out.
    """
    database = tmp_path / "drift.db"
    command.upgrade(_alembic_config(database, monkeypatch), "head")

    for table, columns in Base.metadata.tables.items():
        migrated = set(_columns(database, table))
        modelled = {column.name for column in columns.columns}
        assert migrated == modelled, f"{table} differs"


def test_check_constraints_survive_the_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The database-level rules are in the migration, not only in the models.

    A constraint that exists on the models but not in the migration is a
    constraint the production database does not have.
    """
    database = tmp_path / "constraints.db"
    command.upgrade(_alembic_config(database, monkeypatch), "head")

    checks = _check_constraints(database)

    assert "ck_daily_logs_n_bms_non_negative" in checks
    assert "ck_bm_entries_bristol_type_range" in checks
    # Strain is back: it was dropped with the rest of the per-BM detail, then
    # reinstated. Autogenerate emits the column but not the constraint, because
    # SQLite cannot add one without rebuilding the table, so this assertion is
    # the only thing standing between a regenerated migration and a database
    # with no rule on the column at all.
    assert "ck_bm_entries_strain_range" in checks
    # Urgency and the descriptor flags are still dropped, so their constraints
    # must not linger in the migration either.
    assert "ck_bm_entries_urgency_range" not in checks


@pytest.mark.parametrize(
    ("table", "column", "parent"),
    [("bm_entries", "daily_log_id", "daily_logs"), ("daily_logs", "user_id", "users")],
)
def test_foreign_keys_cascade_in_the_migrated_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    table: str,
    column: str,
    parent: str,
) -> None:
    """`ON DELETE CASCADE` must be in the migration, not just the models."""
    database = tmp_path / f"fk_{table}.db"
    command.upgrade(_alembic_config(database, monkeypatch), "head")

    with sqlite3.connect(database) as connection:
        statement = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()

    assert statement is not None
    ddl = statement[0]
    assert f"FOREIGN KEY({column})" in ddl, f"{table}.{column} has no foreign key"
    assert f"REFERENCES {parent}" in ddl, f"{table}.{column} references the wrong table"
    assert "ON DELETE CASCADE" in ddl, f"{table}.{column} does not cascade"


def test_daily_logs_is_unique_per_user_per_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The uniqueness that makes 'a day is logged' a single fact is migrated.

    Checked by writing rather than by reading DDL, because a UNIQUE constraint
    expressed as a unique index is just as valid as one expressed inline.
    """
    database = tmp_path / "unique.db"
    command.upgrade(_alembic_config(database, monkeypatch), "head")

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (username, display_name, is_admin, is_active,"
            " session_version, timezone, created_at, last_login_at)"
            " VALUES ('cal', 'Cal', 0, 1, 1, 'UTC', '2026-01-01', NULL)"
        )
        connection.execute(
            "INSERT INTO daily_logs (user_id, day, n_bms, created_at, logged_at)"
            " VALUES (1, '2026-01-09', 0, '2026-01-09', '2026-01-09')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO daily_logs (user_id, day, n_bms, created_at,"
                " logged_at) VALUES (1, '2026-01-09', 1, '2026-01-09', '2026-01-09')"
            )
