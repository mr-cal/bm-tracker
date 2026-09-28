"""Declarative base for all ORM models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class every model inherits from."""


def utcnow() -> datetime:
    """Return the current time as a naive UTC datetime.

    Naive UTC is deliberate. SQLite has no native datetime type, so SQLAlchemy
    stores these as ISO-8601 strings, and the lexicographic ordering that every
    date comparison in this app relies on is only correct if the format is
    uniform. One naive-UTC convention is simpler to reason about than mixing
    offsets; converting to a user's timezone happens at the edge, explicitly.

    `occurred_local` is the deliberate exception: it holds naive wall-clock time
    exactly as the user typed it, and is never converted.
    """
    return datetime.now(UTC).replace(tzinfo=None)
