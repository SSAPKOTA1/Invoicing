"""Migration runner: backup before migrating, one transaction per migration, restore on failure."""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from supplier_app.errors import DatabaseError, MigrationError

from .migrations import ALL_MIGRATIONS, Migration

log = logging.getLogger(__name__)

_SCHEMA_VERSION_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_version ("
    " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
)


def split_statements(script: str) -> list[str]:
    """Split a SQL script into complete statements (trigger bodies stay intact)."""
    statements: list[str] = []
    start = 0
    pos = script.find(";")
    while pos != -1:
        chunk = script[start : pos + 1]
        if sqlite3.complete_statement(chunk):
            if chunk.strip():
                statements.append(chunk.strip())
            start = pos + 1
        pos = script.find(";", pos + 1)
    tail = script[start:].strip()
    if tail:
        statements.append(tail)
    return statements


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(_SCHEMA_VERSION_DDL)
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def _backup_file(db_path: Path, backup_dir: Path, version: int) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"pre-migration-v{version}-{stamp}.db"
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return target


def _restore(db_path: Path, backup: Path) -> None:
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    shutil.copy2(backup, db_path)


def migrate(
    db_path: Path | str,
    backup_dir: Path | str | None = None,
    migrations: Sequence[Migration] | None = None,
    target_version: int | None = None,
) -> int:
    """Bring the database at ``db_path`` up to date and return the resulting version.

    Raises :class:`MigrationError` (after restoring the pre-migration backup) when a
    migration fails and :class:`DatabaseError` when the database is newer than the app.
    """
    path = Path(db_path)
    available = list(migrations if migrations is not None else ALL_MIGRATIONS)
    latest = target_version if target_version is not None else available[-1].version
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    backup: Path | None = None
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        version = current_version(conn)
        if version > max(m.version for m in available):
            raise DatabaseError(
                f"Die Datenbank hat Schema-Version {version}, diese Anwendung kennt nur "
                f"{max(m.version for m in available)}. Bitte aktualisieren Sie die Anwendung."
            )
        pending = [m for m in sorted(available, key=lambda m: m.version) if version < m.version <= latest]
        if not pending:
            return version
        if version > 0 and backup_dir is not None:
            conn.close()
            backup = _backup_file(path, Path(backup_dir), version)
            conn = sqlite3.connect(str(path), isolation_level=None)
            conn.execute("PRAGMA foreign_keys = ON")
        for mig in pending:
            try:
                conn.execute("BEGIN IMMEDIATE")
                for stmt in split_statements(mig.sql):
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_version(version, name, applied_at) VALUES (?, ?, ?)",
                    (mig.version, mig.name, datetime.now().isoformat(timespec="seconds")),
                )
                conn.execute("COMMIT")
            except Exception as exc:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                conn.close()
                if backup is not None:
                    _restore(path, backup)
                log.exception("Migration %s failed", mig.version)
                raise MigrationError(
                    f"Die Datenbank-Aktualisierung (Version {mig.version}) ist fehlgeschlagen. "
                    "Der vorherige Stand wurde wiederhergestellt.",
                    hint=str(exc),
                ) from exc
            version = mig.version
        return version
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
