"""One-time import of the data of the old single-user version (a ``supplier.db`` SQLite file plus its ``documents`` folder).

The current program works only with PostgreSQL; this module reads the old file with Python's standard ``sqlite3`` (read-only)
and copies everything into the empty server database."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from supplier_app.backup.dump import is_empty, iter_rows, load_tables
from supplier_app.database.pg import PgDatabase
from supplier_app.errors import BackupError
from supplier_app.settings.local_prefs import PER_USER_KEYS


class _LegacyFile:
    """Read-only view of the old database file with the small query interface the loader needs."""

    def __init__(self, path: Path) -> None:
        try:
            self.conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("SELECT 1 FROM parties LIMIT 1")
        except sqlite3.Error as exc:
            raise BackupError(f"Die Datei '{path.name}' ist keine Datenbank der früheren Programmversion: {exc}") from exc

    def query_all(self, sql: str) -> list[sqlite3.Row]:
        try:
            return self.conn.execute(sql).fetchall()
        except sqlite3.OperationalError:  # a table that older versions did not have yet
            return []

    def close(self) -> None:
        self.conn.close()


def import_legacy_database(db_file: Path | str, target: PgDatabase, documents_dir: Path | str | None = None) -> int:
    """Copy all data (and the document files) of an old ``supplier.db`` into the empty server database.

    ``documents_dir`` defaults to the ``documents`` folder next to the file. The old PIN lock, the old per-PC settings and
    users (there were none) are not copied. Returns the number of copied rows."""
    path = Path(db_file)
    if not path.is_file():
        raise BackupError(f"Die Datei '{path}' wurde nicht gefunden.")
    if not is_empty(target):
        raise BackupError("Der Server enthält bereits Daten. Zum Schutz wird nichts überschrieben.")
    folder = Path(documents_dir) if documents_dir else path.parent / "documents"
    source = _LegacyFile(path)
    try:
        def rows(table: str) -> Iterator[dict[str, Any]]:
            if table == "document_files":
                for row in source.query_all("SELECT id, stored_path FROM documents ORDER BY id"):
                    file = folder / row["stored_path"]
                    if file.is_file():
                        yield {"document_id": row["id"], "content": file.read_bytes()}
                return
            if table == "app_users":
                return
            for row in iter_rows(source, table):
                if table == "settings" and (row["key"].startswith("pin_") or row["key"] in PER_USER_KEYS):
                    continue
                yield row

        return load_tables(target, rows)
    finally:
        source.close()
