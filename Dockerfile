# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY bm_tracker/ bm_tracker/

# setuptools_scm derives the version from git metadata, which is not present in
# the build context. CI passes the real version through this argument.
ARG SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0

RUN uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python .

# ---- Runtime stage ----
FROM python:3.12-slim

# No libpq5, no postgresql-client, no git: the app talks to a local SQLite
# file, so there is no database client and no VCS to install. A leaner image
# matters on a 10GB disk that has already had a disk-full incident.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /build /app

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"

# The SQLite volume is mounted here. Created in the image so a bind mount on a
# fresh volume does not land on a directory that does not exist.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# A single uvicorn worker. SQLite serialises writers, so a second worker buys
# nothing and risks "database is locked" under write contention.
#
# Alembic runs on every start and is a no-op when the schema is already current,
# so deploys need no separate migration step.
CMD ["sh", "-c", "alembic upgrade head && gunicorn --bind 0.0.0.0:8000 --workers 1 --worker-class uvicorn.workers.UvicornWorker 'bm_tracker.app:create_app()'"]
