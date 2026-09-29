"""Command-line entry points.

`bm-tracker admin-create` exists because the first admin has to be created
before anyone can log in, and there is no way to log in to create it. Chicken
and egg, solved with a command rather than a backdoor route.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import click
from sqlalchemy import select

from bm_tracker import auth, migrations
from bm_tracker.database import get_engine, get_session_factory
from bm_tracker.models import User
from bm_tracker.services import audit_service, invite_service, seed_service
from bm_tracker.settings import Settings
from bm_tracker.timezones import DEFAULT_TIMEZONE


@dataclass(frozen=True)
class AdminResult:
    """What `admin-create` produced, for the caller to print."""

    username: str
    created: bool
    setup_path: str | None
    hours_valid: int | None


async def _create_admin(
    settings: Settings,
    username: str,
    display_name: str,
    password: str | None,
    timezone_name: str,
) -> AdminResult:
    """Create (or report) the first administrator.

    Args:
        settings: Runtime configuration, used for the database URL.
        username: The admin's username.
        display_name: The admin's display name.
        password: A password, or `None` to issue a setup link instead.
        timezone_name: An IANA timezone.

    Returns:
        An `AdminResult` describing what happened.

    """
    engine = get_engine(settings.database_url)
    factory = get_session_factory(engine)
    try:
        async with factory() as session:
            slug = username.strip().lower()
            existing = await session.scalar(select(User).where(User.username == slug))
            if existing is not None:
                return AdminResult(
                    slug, created=False, setup_path=None, hours_valid=None
                )

            if password is not None:
                auth.check_password_policy(password, slug)
                password_hash = auth.hash_password(password)
            else:
                password_hash = None

            user = User(
                username=slug,
                display_name=display_name.strip() or slug,
                password_hash=password_hash,
                is_admin=True,
                timezone=timezone_name,
            )
            session.add(user)
            await session.flush()

            setup_path: str | None = None
            hours: int | None = None
            if password_hash is None:
                _, raw_token = await invite_service.issue(session, user)
                setup_path = f"/setup/{raw_token}"
                hours = 72

            await audit_service.record(
                session,
                action="user.create",
                user_id=None,
                entity_type="user",
                entity_id=str(user.id),
                detail={"username": user.username},
            )
            await session.commit()
            return AdminResult(
                slug, created=True, setup_path=setup_path, hours_valid=hours
            )
    finally:
        await engine.dispose()


@click.group()
@click.version_option(package_name="bm-tracker")
def main() -> None:
    """bm-tracker command-line tools."""


@main.command("admin-create")
@click.option("--username", required=True, help="Username for the administrator.")
@click.option("--display-name", default="", help="Name shown in the interface.")
@click.option(
    "--password",
    default=None,
    help="Set this password. Omit to issue a one-time setup link instead.",
)
@click.option(
    "--timezone",
    "timezone_name",
    default=DEFAULT_TIMEZONE,
    help="IANA timezone.",
)
def admin_create(
    username: str, display_name: str, password: str | None, timezone_name: str
) -> None:
    """Create the first administrator.

    Safe to run more than once: if the username exists it reports that and
    changes nothing.
    """
    try:
        settings = Settings()
    except ValueError as exc:
        click.echo(f"Configuration problem: {exc}", err=True)
        sys.exit(1)

    result = asyncio.run(
        _create_admin(settings, username, display_name, password, timezone_name)
    )

    if not result.created:
        click.echo(f"User {result.username!r} already exists. Nothing changed.")
        return

    click.echo(f"Created administrator {result.username!r}.")
    if result.setup_path is not None:
        click.echo(f"  setup link (shown once, valid {result.hours_valid} hours):")
        click.echo(f"    {result.setup_path}")
    else:
        click.echo("  password set directly; they can sign in now.")


@main.command("seed")
@click.option("--users", default=seed_service.DEFAULT_USERS, help="How many people.")
@click.option("--days", default=seed_service.DEFAULT_DAYS, help="Days of history.")
@click.option(
    "--seed", "seed_value", default=42, help="Random seed; same value, same data."
)
@click.option(
    "--password",
    default=None,
    help="Password for every account. Defaults to $BM_TRACKER_E2E_PASSWORD, "
    f"or {seed_service.DEFAULT_PASSWORD!r}.",
)
@click.option(
    "--force", is_flag=True, help="Seed a database that is not obviously a throwaway."
)
def seed(
    users: int, days: int, seed_value: int, password: str | None, *, force: bool
) -> None:
    """Fill the database with a plausible group and its history.

    Destructive: every row is removed first. Refused for any database that is
    not obviously throwaway, so this cannot be pointed at production by accident.
    """
    import os

    try:
        settings = Settings()
    except ValueError as exc:
        click.echo(f"Configuration problem: {exc}", err=True)
        sys.exit(1)

    if not force and not seed_service.is_safe_to_seed(settings.database_url):
        click.echo(
            f"Refusing to wipe {settings.database_url!r}: it is not a local or "
            "e2e database. Pass --force if you really mean it.",
            err=True,
        )
        sys.exit(1)

    chosen = password or os.environ.get(
        "BM_TRACKER_E2E_PASSWORD", seed_service.DEFAULT_PASSWORD
    )

    async def _run() -> seed_service.SeedResult:
        engine = get_engine(settings.database_url)
        factory = get_session_factory(engine)
        try:
            # `make dev-seed` deletes the file first, so the schema may not
            # exist yet. Migrating here — the same thing the container does on
            # startup — keeps the command usable against a clean checkout
            # without a separate step, and records the version so a later
            # autogenerate can still detect drift.
            migrations.upgrade(settings.database_url)
            async with factory() as session:
                return await seed_service.seed(
                    session,
                    users=users,
                    days=days,
                    seed_value=seed_value,
                    password=chosen,
                )
        finally:
            await engine.dispose()

    result = asyncio.run(_run())

    click.echo(
        f"  log one BM as the first account and you will earn "
        f"{seed_service.DEMO_UNLOCK_NAME}"
    )

    click.echo(
        f"Seeded {result.users} users, {result.days} days, {result.bms} BMs\n"
        f"  {result.notes} notes · {result.backfills} backfills · "
        f"{result.quick_entries} quick entries\n"
        f"  password for every account: {chosen!r}"
    )


@main.command("achievements-rebuild")
@click.option(
    "--year", default=None, type=int, help="Year to rebuild. Defaults to now."
)
def achievements_rebuild(year: int | None) -> None:
    """Recompute every user's facts and unlocks from raw data.

    Needed when a new fact is added: users who predate it have no value for it,
    and their achievements would otherwise stay locked forever. Not a migration —
    a command.
    """
    from bm_tracker.achievements import engine
    from bm_tracker.timezones import today_for

    try:
        settings = Settings()
    except ValueError as exc:
        click.echo(f"Configuration problem: {exc}", err=True)
        sys.exit(1)

    target = year if year is not None else today_for("UTC").year

    async def _run() -> int:
        engine_db = get_engine(settings.database_url)
        factory = get_session_factory(engine_db)
        try:
            async with factory() as session:
                written = await engine.rebuild(session, target)
                await session.commit()
                return written
        finally:
            await engine_db.dispose()

    written = asyncio.run(_run())
    click.echo(f"Rebuilt {target}: {written} achievement unlock(s) recorded.")


@main.command("db-backup")
@click.argument("destination")
def db_backup(destination: str) -> None:
    """Write a consistent online backup of the SQLite database.

    Uses SQLite's own backup API rather than copying the file: with WAL active,
    a plain `cp` of a live database can capture a torn write.
    """
    settings = Settings()
    raw_path = settings.database_url.split("///", 1)[-1]
    if not raw_path or raw_path == ":memory:":
        click.echo("Refusing to back up an in-memory database.", err=True)
        sys.exit(1)

    source = Path(raw_path)
    if not source.exists():
        click.echo(f"No database at {source}", err=True)
        sys.exit(1)

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)

    target.chmod(0o600)
    click.echo(f"Backup written to {target}")


if __name__ == "__main__":
    main()


@main.command("note-achievements")
@click.option(
    "--calibrate",
    is_flag=True,
    help="Score the catalogue against the labelled corpus and report thresholds.",
)
def note_achievements(*, calibrate: bool) -> None:
    """Report on the note-achievement catalogue.

    Without `--calibrate` this just says how many there are and whether the
    prototypes are cached, which is the first question when a note that should
    have matched did not.

    With `--calibrate` it embeds the labelled corpus, and reports per
    achievement whether the positives separate from the negatives at all. That
    verdict is the useful part: a threshold cannot fix an achievement whose
    description does not describe its own examples.
    """
    import asyncio

    from bm_tracker.notes import achievements as note_defs
    from bm_tracker.notes import calibration, service

    definitions = note_defs.load()
    settings = Settings()
    click.echo(f"{len(definitions)} note achievements in the catalogue.")

    if not calibrate:
        matcher = service.matcher_from(settings)
        if matcher is None:
            click.echo(
                "No EMBEDDING_API_KEY set, so nothing can be embedded. "
                "Set it to calibrate or to match notes.",
                err=True,
            )
            return
        cache = service.DEFAULT_CACHE_PATH
        click.echo(
            f"prototype cache: {'present' if cache.is_file() else 'not built yet'}"
        )
        return

    matcher = service.matcher_from(settings)
    if matcher is None:
        msg = "EMBEDDING_API_KEY is required to calibrate."
        raise click.ClickException(msg)

    async def run() -> list:
        return await calibration.calibrate(matcher, definitions)  # type: ignore[arg-type]

    verdicts = asyncio.run(run())

    click.echo()
    click.echo(
        f"{'key':24} {'verdict':11} {'worst+':>7} {'best-':>7} "
        f"{'current':>8} {'suggest':>8}"
    )
    click.echo("-" * 72)
    for verdict in verdicts:
        click.echo(
            f"{verdict.key:24} {verdict.verdict:11} "
            f"{verdict.worst_positive:7.3f} {verdict.best_negative:7.3f} "
            f"{verdict.current:8.3f} {verdict.suggested:8.3f}"
        )
    bad = [v for v in verdicts if not v.separable]
    if bad:
        click.echo()
        click.echo(
            f"{len(bad)} of {len(verdicts)} do not separate. Each needs a "
            "different description, more examples, or a stricter guard."
        )
    for verdict in bad:
        click.echo(f"  {verdict.key}: {verdict.note}")
