"""SQLite abstraction layer: one connection, parameterized queries, nested transactions."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from supplier_app.errors import DatabaseError

log = logging.getLogger(__name__)

Params = Sequence[Any] | dict[str, Any]


class Database:
    """Thin wrapper around :mod:`sqlite3`.

    * foreign keys ON, WAL journal, ``sqlite3.Row`` rows
    * only parameterized statements are accepted (``?`` or ``:name``)
    * :meth:`transaction` nests via savepoints
    """

    def __init__(self, path: Path | str, *, timeout: float = 5.0) -> None:
        self.path = str(path)
        self._timeout = timeout
        self._conn: sqlite3.Connection | None = None
        self._depth = 0

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> Database:
        if self._conn is not None:
            return self
        try:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=self._timeout, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute(f"PRAGMA busy_timeout = {int(self._timeout * 1000)}")
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Die Datenbank konnte nicht geöffnet werden.",
                hint="Prüfen Sie, ob die Datei von einem anderen Programm gesperrt ist.",
            ) from exc
        self._conn = conn
        return self

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
                self._depth = 0

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise DatabaseError("Die Datenbank ist nicht geöffnet.")
        return self._conn

    def __enter__(self) -> Database:
        return self.connect()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- statements --------------------------------------------------------
    def execute(self, sql: str, params: Params = ()) -> sqlite3.Cursor:
        try:
            return self.conn.execute(sql, params)
        except sqlite3.IntegrityError:
            raise
        except sqlite3.OperationalError as exc:
            raise self._wrap(exc) from exc

    def executemany(self, sql: str, rows: Iterable[Params]) -> sqlite3.Cursor:
        try:
            return self.conn.executemany(sql, rows)
        except sqlite3.OperationalError as exc:
            raise self._wrap(exc) from exc

    def query_all(self, sql: str, params: Params = ()) -> list[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Params = ()) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Params = (), default: Any = None) -> Any:
        row = self.execute(sql, params).fetchone()
        return default if row is None or row[0] is None else row[0]

    def insert(self, sql: str, params: Params = ()) -> int:
        cur = self.execute(sql, params)
        rowid = cur.lastrowid
        assert rowid is not None
        return int(rowid)

    @staticmethod
    def _wrap(exc: sqlite3.OperationalError) -> DatabaseError:
        text = str(exc).lower()
        if "locked" in text or "busy" in text:
            return DatabaseError(
                "Die Datenbank ist gerade gesperrt.",
                hint="Schließen Sie andere Instanzen der Anwendung und versuchen Sie es erneut.",
            )
        if "disk" in text and "full" in text or "readonly" in text:
            return DatabaseError(
                "Die Datenbank kann nicht geschrieben werden (Speicherplatz voll oder schreibgeschützt)."
            )
        return DatabaseError(f"Datenbankfehler: {exc}")

    # -- transactions ------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Atomic block; nested use creates savepoints. Rolls back on any exception."""
        conn = self.conn
        if self._depth == 0:
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise self._wrap(exc) from exc
            self._depth = 1
            try:
                yield
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")
            finally:
                self._depth = 0
        else:
            name = f"sp{self._depth}"
            conn.execute(f"SAVEPOINT {name}")
            self._depth += 1
            try:
                yield
            except BaseException:
                conn.execute(f"ROLLBACK TO {name}")
                conn.execute(f"RELEASE {name}")
                raise
            else:
                conn.execute(f"RELEASE {name}")
            finally:
                self._depth -= 1

    @property
    def in_transaction(self) -> bool:
        return self._depth > 0

    def schema_version(self) -> int:
        row = self.query_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if row is None:
            return 0
        return int(self.scalar("SELECT MAX(version) FROM schema_version", default=0))

    def integrity_ok(self) -> bool:
        return self.scalar("PRAGMA integrity_check") == "ok"
