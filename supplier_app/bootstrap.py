"""Opens the database, applies migrations and builds the repository bundle."""

from __future__ import annotations

from dataclasses import dataclass

from supplier_app.database.connection import Database
from supplier_app.database.migrator import migrate
from supplier_app.repositories.sqlite_repos import SqliteRepositories
from supplier_app.settings.paths import AppPaths


@dataclass
class Storage:
    paths: AppPaths
    db: Database
    repos: SqliteRepositories

    def close(self) -> None:
        self.db.close()


def open_storage(paths: AppPaths) -> Storage:
    """Create folders, migrate (with backup) and open the database."""
    paths.ensure()
    migrate(paths.database, backup_dir=paths.backups / "migrations")
    db = Database(paths.database).connect()
    return Storage(paths=paths, db=db, repos=SqliteRepositories(db))


def open_memory_storage() -> Storage:
    """In-memory database for tests (no files)."""
    import tempfile
    from pathlib import Path

    from supplier_app.database.migrations import ALL_MIGRATIONS
    from supplier_app.database.migrator import split_statements

    db = Database(":memory:").connect()
    for mig in ALL_MIGRATIONS:
        for stmt in split_statements(mig.sql):
            db.execute(stmt)
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    for mig in ALL_MIGRATIONS:
        db.execute("INSERT INTO schema_version VALUES (?,?,?)", (mig.version, mig.name, "memory"))
    tmp = Path(tempfile.mkdtemp(prefix="supplierapp-mem-"))
    return Storage(paths=AppPaths(tmp).ensure(), db=db, repos=SqliteRepositories(db))
