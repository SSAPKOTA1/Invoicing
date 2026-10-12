"""Shared helpers for the SQLite repositories."""

from __future__ import annotations

from datetime import date

from supplier_app.database.connection import Database
from supplier_app.util.dates import from_iso, now_iso, to_iso


class SqliteRepo:
    """Base class holding the database handle."""

    def __init__(self, db: Database) -> None:
        self.db = db


def d2s(value: date | None) -> str | None:
    return to_iso(value)


def s2d(text: str | None) -> date | None:
    return from_iso(text)


def must_date(text: str) -> date:
    result = from_iso(text)
    assert result is not None
    return result


def stamp(value: str) -> str:
    return value or now_iso()


def like_escape(text: str) -> str:
    """Escape LIKE wildcards; use with ``ESCAPE '\\'``."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
