"""FastAPI application factory for bm-tracker."""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from bm_tracker import icons, times
from bm_tracker import theme as themes
from bm_tracker.database import check_database, get_engine, get_session_factory
from bm_tracker.dependencies import LoginRequiredError, login_required_handler
from bm_tracker.routes import admin, auth, home, log, people, stats
from bm_tracker.settings import Settings

SESSION_COOKIE = "bm_session"

# Anything at or above this is worth a log line even for a static file.
HTTP_BAD_REQUEST = 400
STATIC_PREFIX = "/static/"

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).parent
_TEMPLATES_DIR = _PACKAGE_DIR / "templates"
_STATIC_DIR = _PACKAGE_DIR / "static"


class JSONFormatter(logging.Formatter):
    """Format log records as one JSON object per line.

    Container stdout is a log stream, not a data store; JSON makes it greppable
    by the things that matter when something has gone wrong.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render the record as JSON.

        Args:
            record: The record being emitted.

        Returns:
            A single-line JSON object.

        """
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _configure_logging(settings: Settings) -> None:
    """Install the JSON root handler, unless handlers already exist.

    Skipped when handlers are present so that pytest's `caplog` keeps working.
    """
    if logging.root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))


def _redact(database_url: str) -> str:
    """Return a database URL with any embedded password removed.

    SQLite URLs carry a path rather than a credential, but nothing that could
    be a secret should reach a log line whatever the backend turns out to be.
    """
    if "@" not in database_url:
        return database_url
    scheme, _, rest = database_url.partition("://")
    _, _, host = rest.rpartition("@")
    return f"{scheme}://***@{host}"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Hold the database engine open for the life of the process."""
    settings: Settings = app.state.settings
    engine = get_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = get_session_factory(engine)
    logger.info("bm-tracker starting database=%s", _redact(settings.database_url))
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("bm-tracker shutdown complete")


class HealthResponse(BaseModel):
    """The health endpoint's response body.

    A status string and nothing else. The endpoint is unauthenticated, so it
    must not name the driver, the file path, or the underlying error.
    """

    status: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Configuration to use. Defaults to reading the environment,
            which is what uvicorn's `--factory` mode relies on.

    Returns:
        A configured `FastAPI` instance.

    """
    resolved = settings if settings is not None else Settings()
    _configure_logging(resolved)

    app = FastAPI(
        title="bm-tracker",
        description="A private daily bowel-movement tracker.",
        lifespan=lifespan,
        debug=resolved.debug,
    )
    app.state.settings = resolved

    # The session cookie is the only bearer credential in the app, so it is
    # HttpOnly (no script access), Secure (HTTPS only) and SameSite=Lax. A
    # production boot with no SESSION_SECRET has already been refused by
    # Settings; in development a fixed value keeps `make dev` working.
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolved.session_secret or "development-only-insecure-secret",
        session_cookie=SESSION_COOKIE,
        same_site="lax",
        https_only=resolved.is_production,
        max_age=resolved.session_max_age_days * 24 * 60 * 60,
    )

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    # Cache-bust static assets on process start, so a deploy invalidates every
    # cached stylesheet without having to version the file names.
    cache_bust = str(int(time.time()))
    cast(dict[str, object], templates.env.globals)["cache_bust"] = cache_bust
    # Icons are inlined rather than referenced, so they inherit `currentColor`
    # and an active tab can be a different colour from an inactive one.
    cast(dict[str, object], templates.env.globals)["icon"] = icons.icon
    # The theme module, so the page can apply the colour scheme before the
    # stylesheet loads. The cookie name has to be in the document for that, and
    # duplicating the literal in a template is how the two drift apart.
    cast(dict[str, object], templates.env.globals)["theme"] = themes
    # Times are written through one helper rather than a strftime in each
    # template, so the app cannot end up rendering one page at 07:30 and the
    # next at 7:30 am.
    cast(dict[str, object], templates.env.globals)["clock"] = times.clock
    cast(dict[str, object], templates.env.globals)["stamp"] = times.stamp
    cast(dict[str, object], templates.env.globals)["day_only"] = times.day_only
    cast(dict[str, object], templates.env.globals)["feed_when"] = times.feed_when
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.middleware("http")
    async def _access_log(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Log method, path, status, duration and client for every request.

        Static files are skipped unless something went wrong with one. A page
        pulls down two stylesheets and twenty-odd icons, most of them answered
        with a 304, and logging those buries the two lines anyone actually
        reads. A 404 on a static file is still logged: that is a broken
        reference, and it is exactly what this is for.
        """
        started = time.monotonic()
        response = await call_next(request)
        if response.status_code < HTTP_BAD_REQUEST and request.url.path.startswith(
            STATIC_PREFIX
        ):
            return response
        duration_ms = (time.monotonic() - started) * 1000
        client_host = request.client.host if request.client else "-"
        logger.info(
            "%s %s %d %.1fms client=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            client_host,
        )
        return response

    @app.get("/health", response_model=HealthResponse, tags=["Health"])
    async def health(request: Request) -> HealthResponse | JSONResponse:
        """Report that the process is up and that the database answers.

        Returns:
            200 with `{"status": "ok"}`, or 503 with `{"status": "degraded"}`.

        """
        engine: AsyncEngine = request.app.state.engine
        if await check_database(engine):
            return HealthResponse(status="ok")
        return JSONResponse({"status": "degraded"}, status_code=503)

    app.add_exception_handler(LoginRequiredError, login_required_handler)

    @app.exception_handler(404)
    async def not_found_handler(request: Request, _exc: Exception) -> HTMLResponse:
        """Render a friendly 404 page."""
        app_templates: Jinja2Templates = request.app.state.templates
        return app_templates.TemplateResponse(
            request, "errors/404.html", status_code=404
        )

    @app.exception_handler(500)
    async def server_error_handler(request: Request, _exc: Exception) -> HTMLResponse:
        """Render a friendly 500 page."""
        app_templates: Jinja2Templates = request.app.state.templates
        return app_templates.TemplateResponse(
            request, "errors/500.html", status_code=500
        )

    app.include_router(home.router)
    app.include_router(log.router)
    app.include_router(people.router)
    app.include_router(stats.router)
    app.include_router(auth.router)
    app.include_router(admin.router)

    return app


__all__ = ["HealthResponse", "create_app"]
