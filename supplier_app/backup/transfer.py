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


def transfer_to_shared(local: Storage, folder: Path | str) -> int:
    """Copy database and documents of this PC into an empty shared folder (consistent copy through SQLite's backup
    API). The local data stays untouched. Returns the number of copied files."""
    import shutil
    import sqlite3

    from supplier_app.settings.connection import check_shared_folder

    if local.db.backend != "sqlite":
        raise BackupError("Die Übertragung ist nur aus dem Einzelplatz-Modus möglich.")
    target = check_shared_folder(str(folder))
    if (target / "supplier.db").exists():
        raise BackupError("Im gemeinsamen Ordner liegt bereits eine Datenbank. Zum Schutz wird nichts überschrieben.")
    copied = 0
    dst = sqlite3.connect(str(target / "supplier.db"))
    try:
        local.db.conn.backup(dst)
        dst.execute("PRAGMA journal_mode = DELETE")
    finally:
        dst.close()
    (target / "documents").mkdir(exist_ok=True)
    for src in Path(local.paths.documents).glob("*"):
        if src.is_file():
            shutil.copy2(src, target / "documents" / src.name)
            copied += 1
    return copied + 1
