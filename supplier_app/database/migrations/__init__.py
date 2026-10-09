"""Numbered schema migrations."""

from __future__ import annotations

from dataclasses import dataclass

from . import m001_core, m002_references_search, m003_reporting_indexes


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


ALL_MIGRATIONS: list[Migration] = [
    Migration(m.VERSION, m.NAME, m.SQL) for m in (m001_core, m002_references_search, m003_reporting_indexes)
]
LATEST_VERSION: int = ALL_MIGRATIONS[-1].version
