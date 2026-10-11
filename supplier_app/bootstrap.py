"""Opens the PostgreSQL database, applies migrations and builds the repository bundle."""

from __future__ import annotations

from dataclasses import dataclass

from supplier_app.database.migrator import migrate
from supplier_app.database.pg import PgDatabase
from supplier_app.repositories.pg_repos import PgRepositories
from supplier_app.settings.paths import AppPaths


@dataclass
class Storage:
    paths: AppPaths
    db: PgDatabase
    repos: PgRepositories

    def close(self) -> None:
        self.db.close()


def open_storage(paths: AppPaths, dsn: str) -> Storage:
    """Connect to the server and bring the schema up to date (several PCs starting at once are safe)."""
    paths.ensure()
    db = PgDatabase(dsn).connect()
    try:
        migrate(db)
    except Exception:
        db.close()
        raise
    return Storage(paths=paths, db=db, repos=PgRepositories(db))
