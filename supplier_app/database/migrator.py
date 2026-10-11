"""Migration runner: one transaction per migration (PostgreSQL DDL is transactional), advisory lock for concurrent starts."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime

from supplier_app.errors import DatabaseError, MigrationError

from .migrations import ALL_MIGRATIONS, Migration
from .pg import MIGRATION_LOCK, PgDatabase

log = logging.getLogger(__name__)


def migrate(db: PgDatabase, migrations: Sequence[Migration] | None = None) -> int:
    """Bring the database up to date and return the schema version.

    Several clients starting at the same time migrate exactly once (advisory lock). A failing migration is rolled back
    completely and reported as :class:`MigrationError`; a database that is newer than the program is refused."""
    available = sorted(migrations if migrations is not None else ALL_MIGRATIONS, key=lambda m: m.version)
    latest = available[-1].version
    db.execute(f"SELECT pg_advisory_lock({MIGRATION_LOCK})")
    try:
        db.execute("CREATE TABLE IF NOT EXISTS schema_version (version BIGINT PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
        version = int(db.scalar("SELECT MAX(version) FROM schema_version", default=0))
        if version > latest:
            raise DatabaseError(
                f"Die Datenbank hat Schema-Version {version}, diese Anwendung kennt nur {latest}. "
                "Bitte aktualisieren Sie die Anwendung.")
        for mig in available:
            if mig.version <= version:
                continue
            try:
                with db.transaction():
                    for stmt in mig.statements:
                        db.execute(stmt)
                    db.execute("INSERT INTO schema_version(version, name, applied_at) VALUES (?, ?, ?)",
                               (mig.version, mig.name, datetime.now().isoformat(timespec="seconds")))
            except Exception as exc:
                log.exception("migration %s failed", mig.version)
                raise MigrationError(
                    f"Die Datenbank-Aktualisierung (Version {mig.version}) ist fehlgeschlagen. "
                    "Der vorherige Stand ist unverändert.", hint=str(exc)) from exc
            version = mig.version
        return version
    finally:
        db.execute(f"SELECT pg_advisory_unlock({MIGRATION_LOCK})")
