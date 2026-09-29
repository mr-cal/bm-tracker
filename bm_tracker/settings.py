"""Application settings, loaded from environment variables and env files."""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 32 bytes of entropy. A shorter secret weakens the session cookie's HMAC, and
# refusing to boot on a weak one is cheaper than discovering it later.
MIN_SESSION_SECRET_BYTES = 32


class Settings(BaseSettings):
    """Runtime configuration, resolved from the environment.

    In production the container is given real environment variables by
    `env_file: bm-tracker.env` in the compose file, and those always win. The
    file entries below are a convenience for local development, where a `.env`
    sitting in the working directory is easier than exporting variables.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "bm-tracker.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- database -----------------------------------------------------------
    # The app is async, so this is the ASYNC driver. The alembic environment
    # strips `+aiosqlite` to reach the synchronous one for migrations.
    database_url: str = "sqlite+aiosqlite:///./data/bm_tracker.db"

    # --- application --------------------------------------------------------
    app_env: str = "production"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    debug: bool = False
    log_level: str = "INFO"

    # --- security -----------------------------------------------------------
    session_secret: str = ""
    session_max_age_days: int = Field(default=30, ge=1)

    # --- gamification knobs -------------------------------------------------
    # The rules themselves live in scoring.py as constants; only the ones worth
    # retuning on a running box are settings. See plans/plan-01-bootstrapping.md
    # section 2.5.3.
    quick_entry_window_minutes: int = Field(default=10, ge=1)

    # --- note achievements --------------------------------------------------
    # The only thing in the app that calls a provider, and it is off unless a
    # key is present. Every other achievement is counted, not read, so a private
    # install works with no key at all and simply has no semantic ones.
    embedding_api_key: str = ""
    embedding_base_url: str = "https://openrouter.ai/api/v1"
    # The same model craft-dashboard searches issues with, so a note and a commit
    # land in the same vector space if that ever matters.
    embedding_model: str = "openai/text-embedding-3-small"
    # Narrowed from the model's native 1536. A sixth of the payload for no
    # measurable loss on a cosine comparison, and it is what craft-dashboard
    # stores.
    embedding_dimensions: int = Field(default=1024, ge=64, le=1536)

    @property
    def is_production(self) -> bool:
        """Return whether the app is running in its production configuration."""
        return self.app_env == "production"

    @model_validator(mode="after")
    def _validate_deployment_safety(self) -> Settings:
        """Refuse configurations that would leak data if left on by accident.

        A production deployment with debug on serves tracebacks containing SQL
        and configuration, and a short session secret weakens the cookie's HMAC.
        Both are cheap to refuse and expensive to discover.
        """
        if not self.is_production:
            return self

        if self.debug:
            msg = "DEBUG=true is refused when APP_ENV=production"
            raise ValueError(msg)

        if not self.session_secret:
            msg = "SESSION_SECRET is required when APP_ENV=production"
            raise ValueError(msg)

        if len(self.session_secret.encode()) < MIN_SESSION_SECRET_BYTES:
            msg = (
                "SESSION_SECRET must be at least "
                f"{MIN_SESSION_SECRET_BYTES} bytes when APP_ENV=production"
            )
            raise ValueError(msg)

        return self
