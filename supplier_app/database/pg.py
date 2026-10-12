"""PostgreSQL backend (multi-user server mode) with the same interface as :class:`Database`.

* statements are written with ``?`` placeholders like for SQLite and translated here
* rows support ``row["name"]`` and ``row[0]`` like :class:`sqlite3.Row`
* every top-level transaction takes a global advisory lock, so writers are serialised exactly like
  SQLite's ``BEGIN IMMEDIATE`` (no lost updates between users, payments cannot be allocated twice)
* inside a transaction each write runs in a savepoint, so a rejected statement (duplicate ...) does not abort
  the whole transaction - the behaviour the repositories rely on
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from supplier_app.errors import DatabaseError

from .errors import PG_AVAILABLE, psycopg

log = logging.getLogger(__name__)

Params = Sequence[Any] | dict[str, Any]

#: global lock number (one per application database)
WRITE_LOCK = 7_310_001
MIGRATION_LOCK = 7_310_002
_WRITE_RE = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE)\b", re.I)


class Row(tuple):
    """Result row: index and column-name access (like ``sqlite3.Row``)."""

    def __new__(cls, index: dict[str, int], values: Iterable[Any]) -> Row:
        obj = super().__new__(cls, values)
        obj._index = index
        return obj

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self) -> list[str]:
        return list(self._index)


def _row_factory(cursor: Any):
    names = [c.name for c in cursor.description or []]
    index = {n: i for i, n in enumerate(names)}

    def make(values: Sequence[Any]) -> Row:
        return Row(index, values)

    return make


def translate_sql(sql: str) -> str:
    """``?`` -> ``%s`` (outside string literals), literal ``%`` doubled, ``LIKE`` -> ``ILIKE`` (SQLite's LIKE ignores case)."""
    out: list[str] = []
    quote = ""
    for ch in sql:
        if quote:
            out.append("%%" if ch == "%" else ch)
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
    text = "".join(out)
    return re.sub(r"\bLIKE\b", "ILIKE", text)


def _clean_params(params: Params) -> Params:
    if isinstance(params, dict):
        return {k: int(v) if isinstance(v, bool) else v for k, v in params.items()}
    return [int(p) if isinstance(p, bool) else p for p in params]


class _IntegralNumeric:
    """SUM() over BIGINT is NUMERIC in PostgreSQL: hand integers to the code like SQLite does."""

    @staticmethod
    def register(conn: Any) -> None:
        from psycopg.adapt import Loader

        class NumericLoader(Loader):
            def load(self, data):  # type: ignore[no-untyped-def]
                value = Decimal(bytes(data).decode())
                return int(value) if value == value.to_integral_value() else value

        conn.adapters.register_loader("numeric", NumericLoader)


class PgDatabase:
    """Thin wrapper around a psycopg 3 connection (autocommit, explicit transactions)."""

    backend = "postgres"

    def __init__(self, dsn: str, *, timeout: float = 10.0, lock_timeout: float = 30.0) -> None:
        if not PG_AVAILABLE:
            raise DatabaseError("Der PostgreSQL-Treiber (psycopg) ist nicht installiert.")
        self.dsn = dsn
        self._timeout = timeout
        self._lock_timeout = lock_timeout
        self._conn: Any = None
        self._depth = 0
        self.read_only = False  # set for the 'Lesen' role: any write statement is refused
        self._user_name = ""

    # -- lifecycle -------------------------------------------------------------------------------
    def connect(self) -> PgDatabase:
        if self._conn is not None and not self._conn.closed:
            return self
        try:
            conn = psycopg.connect(self.dsn, autocommit=True, connect_timeout=int(self._timeout), row_factory=_row_factory)
            conn.execute(f"SET lock_timeout = {int(self._lock_timeout * 1000)}")
            conn.execute("SET client_min_messages = warning")
            _IntegralNumeric.register(conn)
            if self._user_name:
                conn.execute("SELECT set_config('supplier.user', %s, false)", (self._user_name,))
        except psycopg.Error as exc:
            raise DatabaseError(
                "Die Verbindung zum Datenbank-Server ist fehlgeschlagen.",
                hint=_first_line(exc),
            ) from exc
        self._conn = conn
        self._depth = 0
        return self

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
                self._depth = 0

    @property
    def user_name(self) -> str:
        return self._user_name

    @user_name.setter
    def user_name(self, name: str) -> None:
        """Who is logged in: audit log and the 'changed by' field of the live-refresh counter."""
        self._user_name = name
        if self._conn is not None and not self._conn.closed:
            self._conn.execute("SELECT set_config('supplier.user', %s, false)", (name,))

    @property
    def conn(self) -> Any:
        if self._conn is None or self._conn.closed:
            if self._depth:
                raise DatabaseError("Die Verbindung zum Datenbank-Server wurde während einer Buchung unterbrochen.")
            self.connect()  # transparent reconnect between operations
        return self._conn

    def __enter__(self) -> PgDatabase:
        return self.connect()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- statements --------------------------------------------------------------------------------
    def _guard(self, sql: str) -> None:
        if self.read_only and "app_users" not in sql and not re.match(r"^\s*(?:SELECT|WITH|SHOW|SET|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE)\b", sql, re.I):
            raise DatabaseError("Ihre Benutzerrolle erlaubt nur Lesen. Änderungen sind nicht möglich.")

    def execute(self, sql: str, params: Params = ()) -> Any:
        self._guard(sql)
        text, args = translate_sql(sql), _clean_params(params)
        conn = self.conn
        try:
            if self._depth and _WRITE_RE.match(sql):
                # statement-level rollback like SQLite: a rejected insert must not abort the transaction
                conn.execute("SAVEPOINT stmt")
                try:
                    cur = conn.execute(text, args)
                except BaseException:
                    conn.execute("ROLLBACK TO SAVEPOINT stmt")
                    conn.execute("RELEASE SAVEPOINT stmt")
                    raise
                conn.execute("RELEASE SAVEPOINT stmt")
                return cur
            return conn.execute(text, args)
        except psycopg.errors.IntegrityError:
            raise
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            raise self._wrap(exc) from exc
        except psycopg.Error as exc:
            raise DatabaseError(f"Datenbankfehler: {_first_line(exc)}") from exc

    def executemany(self, sql: str, rows: Iterable[Params]) -> None:
        for row in rows:
            self.execute(sql, row)

    def query_all(self, sql: str, params: Params = ()) -> list[Row]:
        return self.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Params = ()) -> Row | None:
        return self.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Params = (), default: Any = None) -> Any:
        row = self.execute(sql, params).fetchone()
        return default if row is None or row[0] is None else row[0]

    def insert(self, sql: str, params: Params = ()) -> int:
        if " returning " not in sql.lower():
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
        row = self.execute(sql, params).fetchone()
        assert row is not None
        return int(row[0])

    @staticmethod
    def _wrap(exc: Exception) -> DatabaseError:
        text = str(exc).lower()
        if "lock timeout" in text or "could not obtain lock" in text or "deadlock" in text:
            return DatabaseError("Die Datenbank ist gerade durch einen anderen Benutzer belegt.",
                                 hint="Bitte versuchen Sie es in wenigen Sekunden erneut.")
        return DatabaseError("Die Verbindung zum Datenbank-Server wurde unterbrochen.",
                             hint="Prüfen Sie Netzwerk und Server; die Anwendung verbindet sich beim nächsten Vorgang neu.")

    # -- transactions ------------------------------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Atomic block (global write lock); nested use creates savepoints. Rolls back on any exception."""
        conn = self.conn
        if self._depth == 0:
            try:
                conn.execute("BEGIN")
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK,))
            except psycopg.Error as exc:
                try:
                    conn.execute("ROLLBACK")
                except psycopg.Error:
                    pass
                raise self._wrap(exc) from exc
            self._depth = 1
            try:
                yield
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except psycopg.Error:
                    self.close()
                raise
            else:
                try:
                    conn.execute("COMMIT")
                except psycopg.Error as exc:
                    raise self._wrap(exc) from exc
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

    # -- meta ----------------------------------------------------------------------------------------
    def schema_version(self) -> int:
        if self.scalar("SELECT to_regclass('schema_version')") is None:
            return 0
        return int(self.scalar("SELECT MAX(version) FROM schema_version", default=0))

    def integrity_ok(self) -> bool:
        return self.scalar("SELECT 1") == 1

    def data_version(self) -> int:
        """Counter that changes whenever any user changed data (see migration 5); used for live refresh."""
        return int(self.scalar("SELECT version FROM data_version WHERE id=1", default=0))

    def data_changed_by(self) -> str:
        return str(self.scalar("SELECT changed_by FROM data_version WHERE id=1", default=""))


def _first_line(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
