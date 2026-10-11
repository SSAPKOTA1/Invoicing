"""Numbered schema migrations (native PostgreSQL SQL, one list of statements per version)."""

from __future__ import annotations

from dataclasses import dataclass

from . import m001_core, m002_references_search, m003_reporting_indexes, m004_companies_hotels, m005_users_sync


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


ALL_MIGRATIONS: list[Migration] = [
    Migration(m.VERSION, m.NAME, tuple(m.STATEMENTS))
    for m in (m001_core, m002_references_search, m003_reporting_indexes, m004_companies_hotels, m005_users_sync)
]
LATEST_VERSION: int = ALL_MIGRATIONS[-1].version
