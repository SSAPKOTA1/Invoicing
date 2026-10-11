"""Move a single-user (local SQLite) installation to a PostgreSQL server."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from supplier_app.backup.dump import copy_database, is_empty
from supplier_app.bootstrap import Storage
from supplier_app.database.migrator import migrate_postgres
from supplier_app.database.pg import PgDatabase
from supplier_app.errors import BackupError
from supplier_app.settings.connection import ConnectionConfig


def transfer_to_server(local: Storage, config: ConnectionConfig, progress: Callable[[str], None] | None = None) -> int:
    """Copy all data and document files of ``local`` into the (empty) server database. Returns the number of rows.

    The local data stays untouched, so the transfer can be repeated or abandoned. Users are created on the server
    afterwards (the first start asks for the administrator)."""
    if local.db.backend != "sqlite":
        raise BackupError("Die Übertragung ist nur aus dem Einzelplatz-Modus möglich.")
    target = PgDatabase(config.dsn()).connect()
    try:
        migrate_postgres(target)
        if not is_empty(target):
            raise BackupError("Der Server enthält bereits Daten. Zum Schutz wird nichts überschrieben.")
        return copy_database(local.db, target, Path(local.paths.documents), progress)
    finally:
        target.close()
