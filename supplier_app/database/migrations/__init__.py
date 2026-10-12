"""Numbered schema migrations (written in SQLite dialect; PostgreSQL gets a translation plus ``PG_EXTRA``)."""

from __future__ import annotations

from dataclasses import dataclass

from . import (
    m001_core,
    m002_references_search,
    m003_reporting_indexes,
    m004_companies_hotels,
    m005_users_sync,
    m006_refs_assignment,
    m007_recurring,
)


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    pg_extra: tuple[str, ...] = ()


ALL_MIGRATIONS: list[Migration] = [
    Migration(m.VERSION, m.NAME, m.SQL, tuple(getattr(m, "PG_EXTRA", ())))
    for m in (m001_core, m002_references_search, m003_reporting_indexes, m004_companies_hotels, m005_users_sync,
              m006_refs_assignment, m007_recurring)
]
LATEST_VERSION: int = ALL_MIGRATIONS[-1].version
