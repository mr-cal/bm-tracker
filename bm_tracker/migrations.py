"""Running Alembic from inside the application.

The container runs `alembic upgrade head` before gunicorn, and the seeder runs
this instead of `Base.metadata.create_all`. That is not a stylistic preference:
`create_all` builds whatever the models say today without recording a version, so
Alembic still believes the database is unmigrated and the next
`alembic revision --autogenerate` refuses to run. A seeder that quietly took a
different path from production is a seeder that can be right where the container
is wrong.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
ALEMBIC_DIR = REPO_ROOT / "alembic"


def config_for(database_url: str) -> Config:
    """Return an Alembic config pointed at a database.

    The URL is swapped onto a synchronous driver: Alembic's env.py is not
    async-aware, and handing it the app's `+aiosqlite` URL makes it open the
    file with the wrong driver.

    Args:
        database_url: The application's database URL.

    Returns:
        A configured `Config`.

    """
    url = make_url(database_url)
    sync_url = url.set(drivername=url.drivername.replace("+aiosqlite", ""))
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    # `env.py` reads this; escaping guards a Windows path or a password with a
    # percent sign in it.
    config.set_main_option(
        "sqlalchemy.url", sync_url.render_as_string().replace("%", "%%")
    )
    return config


def upgrade(database_url: str, revision: str = "head") -> None:
    """Bring a database up to a revision.

    Args:
        database_url: The application's database URL.
        revision: The target revision, "head" unless told otherwise.

    """
    command.upgrade(config_for(database_url), revision)
